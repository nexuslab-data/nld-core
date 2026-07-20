import json
from typing import Any, get_origin

from nld.connector.snowflake.snowflake_connector import SnowflakeConnector
from nld.pydantic import NldBaseModel, NldBaseModelManager
from nld.pydantic.field_utils import TS_INSERTED_AT, TS_UPDATED_AT
from nld.utils.sqlglot import (
    literal_value,
)

from .structure_mapper import SnowflakePydanticStructureMapper

SNOWFLAKE_DIALECT = "snowflake"


def _sf_table_ref(schema: str, table: str) -> str:
    """Build an unquoted Snowflake table reference."""
    return f"{schema}.{table}"


def _sf_cols(columns: list[str]) -> str:
    """Build a comma-separated unquoted column list."""
    return ", ".join(columns)


def _get_json_serialized_fields(model_class: type[NldBaseModel]) -> list[str]:
    """Return field names that are stored as JSON strings in Snowflake.

    Dict, list, and NldBaseModel fields are serialized to JSON TEXT on
    write (see SnowflakePydanticStructureMapper.prepare_value_for_target).
    This function identifies those fields so they can be deserialized
    back on read.
    """
    fields = []
    for field_name, field_info in model_class.model_fields.items():
        unwrapped = NldBaseModel._unwrap_optional(field_info.annotation)
        origin = get_origin(unwrapped)
        if origin in (dict, list):
            fields.append(field_name)
        elif isinstance(unwrapped, type) and issubclass(unwrapped, NldBaseModel):
            fields.append(field_name)
    return fields


class NldBaseModelSnowflakeManager(NldBaseModelManager):
    """Manages Pydantic model persistence operations on Snowflake.

    Provides methods to create tables, insert, update, upsert, and read
    Pydantic model instances using Snowflake SQL syntax.

    When track_timestamps is enabled, two database-only columns are managed
    automatically:
    - ts_inserted_at: set to CURRENT_TIMESTAMP() on first insert, never updated.
    - ts_updated_at: set to CURRENT_TIMESTAMP() on every insert or update.
    """

    _TIMESTAMP_DEFAULT: str = "CURRENT_TIMESTAMP()"

    def __init__(self, connector: SnowflakeConnector) -> None:
        """Initialize the manager with a Snowflake connector."""
        self.connector = connector
        self.structure_mapper = SnowflakePydanticStructureMapper()

    def _prepare_value(self, value: Any) -> Any:
        """Prepare a value for insertion into Snowflake."""
        return self.structure_mapper.prepare_value_for_target(value)

    def _to_sql_literal(self, value: Any) -> str:
        """Convert a prepared value to a SQL literal for Snowflake."""
        prepared = self._prepare_value(value)
        return literal_value(prepared, dialect=SNOWFLAKE_DIALECT)

    def insert_model(
        self,
        model: NldBaseModel,
        schema_name: str,
        table_name: str,
        commit: bool = True,
        exclude_fields: set[str] | None = None,
        track_timestamps: bool = False,
    ) -> None:
        """Insert a Pydantic model instance into a Snowflake table."""
        data = model.model_dump(exclude=exclude_fields)
        columns = list(data.keys())
        value_strings = [self._to_sql_literal(data[col]) for col in columns]

        if track_timestamps:
            columns.append(TS_INSERTED_AT)
            value_strings.append("CURRENT_TIMESTAMP()")
            columns.append(TS_UPDATED_AT)
            value_strings.append("CURRENT_TIMESTAMP()")

        table_ref = _sf_table_ref(
            schema_name,
            table_name,
        )
        cols = _sf_cols(
            columns,
        )
        vals = ", ".join(value_strings)

        insert_query = f"INSERT INTO {table_ref} ({cols}) VALUES ({vals})"
        self.connector.execute_query(insert_query)

    def update_model(
        self,
        model: NldBaseModel,
        schema_name: str,
        table_name: str,
        commit: bool = True,
        exclude_fields: set[str] | None = None,
        track_timestamps: bool = False,
    ) -> None:
        """Update a Pydantic model instance in a Snowflake table."""
        structure = self.structure_mapper.get_structure(model.__class__)
        if not structure.has_primary_key():
            raise ValueError(
                f"The base model {model.__class__.__name__} has no primary "
                "key and thus cannot be updated."
            )
        where_fields = [field.name for field in structure.get_primary_key_fields()]
        data = model.model_dump(exclude=exclude_fields)
        update_fields = [f for f in data.keys() if f not in where_fields]

        if not update_fields:
            raise ValueError("No fields to update after excluding where_fields")

        set_parts = [
            f"{field} = {self._to_sql_literal(data[field])}" for field in update_fields
        ]

        if track_timestamps:
            set_parts.append(f"{TS_UPDATED_AT} = CURRENT_TIMESTAMP()")

        set_clause = ", ".join(set_parts)

        dml_builder = self.connector.get_dml_builder()
        where_parts = [
            dml_builder.equality_clause(
                field=field,
                value=self._prepare_value(data[field]),
            )
            for field in where_fields
        ]
        where_clause = dml_builder.and_clause(where_parts)

        table_ref = _sf_table_ref(
            schema_name,
            table_name,
        )
        update_query = f"UPDATE {table_ref} SET {set_clause} WHERE {where_clause}"
        self.connector.execute_query(update_query)

    def upsert_model(
        self,
        model: NldBaseModel,
        schema_name: str,
        table_name: str,
        conflict_fields: list[str] | None = None,
        commit: bool = True,
        exclude_fields: set[str] | None = None,
        track_timestamps: bool = False,
    ) -> None:
        """Upsert a Pydantic model using Snowflake MERGE INTO syntax."""
        structure = self.structure_mapper.get_structure(model.__class__)

        if conflict_fields is None:
            if not structure.has_primary_key():
                raise ValueError(
                    f"The base model {model.__class__.__name__} has no primary "
                    "key and conflict_fields parameter was not provided."
                )
            conflict_fields = [
                field.name for field in structure.get_primary_key_fields()
            ]

        data = model.model_dump(exclude=exclude_fields)
        columns = list(data.keys())
        value_strings = [self._to_sql_literal(data[col]) for col in columns]

        if track_timestamps:
            columns.append(TS_INSERTED_AT)
            value_strings.append("CURRENT_TIMESTAMP()")
            columns.append(TS_UPDATED_AT)
            value_strings.append("CURRENT_TIMESTAMP()")

        update_fields = [f for f in columns if f not in conflict_fields]

        if not update_fields:
            raise ValueError(
                "No fields to update in conflict resolution "
                "after excluding conflict_fields"
            )

        table_ref = _sf_table_ref(
            schema_name,
            table_name,
        )

        # Build source SELECT clause
        source_parts = [
            f"{val} AS {col}" for col, val in zip(columns, value_strings, strict=False)
        ]
        source_select = ", ".join(source_parts)

        # Build ON clause for matching
        on_parts = [f"target.{cf} = source.{cf}" for cf in conflict_fields]
        on_clause = " AND ".join(on_parts)

        # Build UPDATE SET clause
        timestamp_columns = (
            {TS_INSERTED_AT, TS_UPDATED_AT} if track_timestamps else set()
        )
        update_parts = [
            f"{field} = source.{field}"
            for field in update_fields
            if field not in timestamp_columns
        ]
        if track_timestamps:
            update_parts.append(f"{TS_UPDATED_AT} = CURRENT_TIMESTAMP()")
        update_set = ", ".join(update_parts)

        data_cols_for_comparison = [
            field for field in update_fields if field not in timestamp_columns
        ]
        if data_cols_for_comparison:
            change_conditions = " OR ".join(
                f"target.{col} IS DISTINCT FROM source.{col}"
                for col in data_cols_for_comparison
            )
            matched_clause = (
                f"WHEN MATCHED AND ({change_conditions}) THEN UPDATE SET {update_set} "
            )
        else:
            matched_clause = f"WHEN MATCHED THEN UPDATE SET {update_set} "

        # Build INSERT clause
        insert_cols = _sf_cols(
            columns,
        )
        insert_vals = ", ".join(f"source.{col}" for col in columns)

        merge_query = (
            f"MERGE INTO {table_ref} AS target "
            f"USING (SELECT {source_select}) AS source "
            f"ON {on_clause} "
            f"{matched_clause}"
            f"WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})"
        )
        self.connector.execute_query(merge_query)

    def read_model(
        self,
        model_class: type[NldBaseModel],
        schema_name: str,
        table_name: str,
        where_conditions: dict[str, Any] | None = None,
        order_by: list[str] | None = None,
        exclude_fields: set[str] | None = None,
    ) -> NldBaseModel | None:
        """Read a single Pydantic model instance from a Snowflake table."""
        models = self.read_models(
            model_class=model_class,
            schema_name=schema_name,
            table_name=table_name,
            where_conditions=where_conditions,
            limit=1,
            order_by=order_by,
            exclude_fields=exclude_fields,
        )
        return models[0] if models else None

    def read_models(
        self,
        model_class: type[NldBaseModel],
        schema_name: str,
        table_name: str,
        where_conditions: dict[str, Any] | None = None,
        limit: int | None = None,
        order_by: list[str] | None = None,
        exclude_fields: set[str] | None = None,
    ) -> list[NldBaseModel]:
        """Read multiple Pydantic model instances from a Snowflake table."""
        table_ref = _sf_table_ref(
            schema_name,
            table_name,
        )

        if exclude_fields:
            all_field_names = list(model_class.model_fields.keys())
            selected_columns = [
                field_name
                for field_name in all_field_names
                if field_name not in exclude_fields
            ]
            cols = _sf_cols(
                selected_columns,
            )
            query_str = f"SELECT {cols} FROM {table_ref}"
        else:
            query_str = f"SELECT * FROM {table_ref}"

        if where_conditions:
            dml_builder = self.connector.get_dml_builder()
            conditions = [
                dml_builder.equality_clause(
                    field=field,
                    value=value,
                )
                for field, value in where_conditions.items()
            ]
            query_str += f" WHERE {dml_builder.and_clause(conditions)}"

        if order_by:
            order_parts = []
            for field in order_by:
                if field.startswith("-"):
                    order_parts.append(f"{field[1:]} DESC")
                else:
                    order_parts.append(f"{field} ASC")
            query_str += f" ORDER BY {', '.join(order_parts)}"

        if limit is not None:
            query_str += f" LIMIT {literal_value(limit, dialect=SNOWFLAKE_DIALECT)}"

        result = self.connector.execute_query(query_str)
        if result.failed():
            return []

        # Use the raw records helper rather than the pandas DataFrame view:
        # pandas promotes NULLs in numeric/timestamp columns to NaN (a float),
        # which Pydantic then rejects on ``int | None`` / ``datetime | None``
        # fields with "'float' object cannot be interpreted as an integer".
        json_fields = _get_json_serialized_fields(model_class)

        models = []
        for row in result.get_result_records():
            for field_name in json_fields:
                if (
                    field_name in row
                    and isinstance(row[field_name], str)
                    and row[field_name]
                ):
                    row[field_name] = json.loads(row[field_name])
            models.append(model_class.model_validate(row))

        return models
