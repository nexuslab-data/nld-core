from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nld.connector.duckdb.engine.duckdb_native.connector import (
    DuckDBSQLConnector,
)
from nld.pydantic import NldBaseModel, NldBaseModelManager
from nld.pydantic.field_utils import TS_INSERTED_AT, TS_UPDATED_AT
from nld.utils.sqlglot import (
    identifier_list,
    literal_value,
    quote_identifier,
    quote_table,
)

from .structure_mapper import DuckDBPydanticStructureMapper

if TYPE_CHECKING:
    from nld.structure import Structure

from nld.connector.duckdb.constants import DUCKDB_DIALECT


class NldBaseModelDuckDBManager(NldBaseModelManager):
    """Manages Pydantic model persistence operations on DuckDB.

    Provides insert, update, upsert, and read operations for
    Pydantic model instances against a DuckDB database.

    Note: the ``commit`` parameter accepted by write methods is
    present for API compatibility with the base class but has no
    effect.  Each operation runs inside its own transaction via
    ``execute_query`` which commits automatically.
    """

    def __init__(self, connector: DuckDBSQLConnector) -> None:
        self.connector = connector
        self.structure_mapper = DuckDBPydanticStructureMapper()

    def _prepare_value(self, value: Any) -> Any:
        return self.structure_mapper.prepare_value_for_target(value)

    def _create_functional_key_index(
        self,
        structure: Structure,
        table_name: str,
        table_path: str,
        use_functional_key_as_primary: bool,
    ) -> None:
        from nld.structure import StructureCharacterisationDefinitionNames

        if use_functional_key_as_primary:
            return

        functional_key = structure.get_characterisation(
            StructureCharacterisationDefinitionNames.FUNCTIONAL_KEY
        )
        if functional_key and functional_key.linked_fields:
            constraint_name = f"{functional_key.name}_{table_name}".lower()
            self.connector.create_index(
                index_name=constraint_name,
                table_path=table_path,
                columns=functional_key.linked_fields,
                unique=False,
            )

    def insert_model(
        self,
        model: NldBaseModel,
        schema_name: str,
        table_name: str,
        commit: bool = True,
        exclude_fields: set[str] | None = None,
        track_timestamps: bool = False,
    ) -> None:
        data = model.model_dump(exclude=exclude_fields)
        columns = list(data.keys())
        value_strings = [
            literal_value(
                self._prepare_value(data[col]),
                dialect=DUCKDB_DIALECT,
            )
            for col in columns
        ]

        if track_timestamps:
            columns.append(TS_INSERTED_AT)
            value_strings.append("CURRENT_TIMESTAMP")
            columns.append(TS_UPDATED_AT)
            value_strings.append("CURRENT_TIMESTAMP")

        table_ref = quote_table(
            schema=schema_name,
            table=table_name,
            dialect=DUCKDB_DIALECT,
        )
        cols = identifier_list(columns, dialect=DUCKDB_DIALECT)
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
        structure = self.structure_mapper.get_structure(model.__class__)
        if not structure.has_primary_key():
            raise ValueError(
                f"The base model {model.__class__.__name__} has no "
                "primary key and thus cannot be updated."
            )
        where_fields = [field.name for field in structure.get_primary_key_fields()]
        data = model.model_dump(exclude=exclude_fields)
        update_fields = [f for f in data.keys() if f not in where_fields]

        if not update_fields:
            raise ValueError("No fields to update after excluding where_fields")

        set_parts = [
            f"{quote_identifier(field, dialect=DUCKDB_DIALECT)} = "
            f"{literal_value(self._prepare_value(data[field]), dialect=DUCKDB_DIALECT)}"
            for field in update_fields
        ]

        if track_timestamps:
            quoted_ts = quote_identifier(TS_UPDATED_AT, dialect=DUCKDB_DIALECT)
            set_parts.append(f"{quoted_ts} = CURRENT_TIMESTAMP")

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

        table_ref = quote_table(
            schema=schema_name,
            table=table_name,
            dialect=DUCKDB_DIALECT,
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
        structure = self.structure_mapper.get_structure(model.__class__)

        if conflict_fields is None:
            if not structure.has_primary_key():
                raise ValueError(
                    f"The base model {model.__class__.__name__} has "
                    "no primary key and conflict_fields parameter "
                    "was not provided."
                )
            conflict_fields = [
                field.name for field in structure.get_primary_key_fields()
            ]

        data = model.model_dump(exclude=exclude_fields)
        columns = list(data.keys())
        value_strings = [
            literal_value(
                self._prepare_value(data[col]),
                dialect=DUCKDB_DIALECT,
            )
            for col in columns
        ]

        if track_timestamps:
            columns.append(TS_INSERTED_AT)
            value_strings.append("CURRENT_TIMESTAMP")
            columns.append(TS_UPDATED_AT)
            value_strings.append("CURRENT_TIMESTAMP")

        update_fields = [f for f in columns if f not in conflict_fields]

        if not update_fields:
            raise ValueError(
                "No fields to update in conflict resolution "
                "after excluding conflict_fields"
            )

        timestamp_columns = (
            {TS_INSERTED_AT, TS_UPDATED_AT} if track_timestamps else set()
        )
        update_parts = [
            f"{quote_identifier(field, dialect=DUCKDB_DIALECT)} = "
            f"EXCLUDED.{quote_identifier(field, dialect=DUCKDB_DIALECT)}"
            for field in update_fields
            if field not in timestamp_columns
        ]

        if track_timestamps:
            quoted_ts = quote_identifier(TS_UPDATED_AT, dialect=DUCKDB_DIALECT)
            # Use NOW() instead of CURRENT_TIMESTAMP: DuckDB resolves
            # bare identifiers as column references first inside
            # ON CONFLICT DO UPDATE SET, so CURRENT_TIMESTAMP would
            # be misinterpreted as a column name.
            update_parts.append(f"{quoted_ts} = NOW()")

        update_set = ", ".join(update_parts)

        # Change-detection WHERE clause: only update when at least one
        # data column actually changed.  This prevents bumping
        # ts_updated_at on no-op upserts (same behavior as PG manager).
        data_cols_for_comparison = [
            field for field in update_fields if field not in timestamp_columns
        ]
        if data_cols_for_comparison:
            where_parts = [
                f"{quote_identifier(table_name, dialect=DUCKDB_DIALECT)}"
                f".{quote_identifier(col, dialect=DUCKDB_DIALECT)}"
                f" IS DISTINCT FROM "
                f"EXCLUDED.{quote_identifier(col, dialect=DUCKDB_DIALECT)}"
                for col in data_cols_for_comparison
            ]
            change_where = f" WHERE ({' OR '.join(where_parts)})"
        else:
            change_where = ""

        table_ref = quote_table(
            schema=schema_name,
            table=table_name,
            dialect=DUCKDB_DIALECT,
        )
        cols = identifier_list(columns, dialect=DUCKDB_DIALECT)
        vals = ", ".join(value_strings)
        conflict_cols = identifier_list(conflict_fields, dialect=DUCKDB_DIALECT)

        upsert_query = (
            f"INSERT INTO {table_ref} ({cols}) VALUES ({vals}) "
            f"ON CONFLICT ({conflict_cols}) DO UPDATE SET {update_set}"
            f"{change_where}"
        )
        self.connector.execute_query(upsert_query)

    def read_model(
        self,
        model_class: type[NldBaseModel],
        schema_name: str,
        table_name: str,
        where_conditions: dict[str, Any] | None = None,
        order_by: list[str] | None = None,
        exclude_fields: set[str] | None = None,
    ) -> NldBaseModel | None:
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
        table_ref = quote_table(
            schema=schema_name,
            table=table_name,
            dialect=DUCKDB_DIALECT,
        )

        if exclude_fields:
            all_field_names = list(model_class.model_fields.keys())
            selected_columns = [f for f in all_field_names if f not in exclude_fields]
            cols = identifier_list(selected_columns, dialect=DUCKDB_DIALECT)
            query_str = f"SELECT {cols} FROM {table_ref}"
        else:
            query_str = f"SELECT * FROM {table_ref}"

        if where_conditions:
            dml_builder = self.connector.get_dml_builder()
            conditions = [
                dml_builder.equality_clause(field=field, value=value)
                for field, value in where_conditions.items()
            ]
            where = dml_builder.and_clause(conditions)
            query_str += f" WHERE {where}"

        if order_by:
            order_parts = []
            for field in order_by:
                if field.startswith("-"):
                    quoted = quote_identifier(field[1:], dialect=DUCKDB_DIALECT)
                    order_parts.append(f"{quoted} DESC")
                else:
                    quoted = quote_identifier(field, dialect=DUCKDB_DIALECT)
                    order_parts.append(f"{quoted} ASC")
            query_str += f" ORDER BY {', '.join(order_parts)}"

        if limit is not None:
            if not isinstance(limit, int):
                raise TypeError(f"limit must be int, got {type(limit).__name__}")
            query_str += f" LIMIT {literal_value(limit, dialect=DUCKDB_DIALECT)}"

        result = self.connector.execute_query(query_str)
        df = result.get_output_data_as_df()

        models = []
        for row in df.to_dict("records"):
            models.append(model_class.model_validate(row))

        return models
