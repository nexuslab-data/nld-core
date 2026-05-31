import json
import types
import typing
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from nld.connector.postgresql.engine.psycopg2.connector import Psycopg2SQLConnector
from nld.pydantic import NldBaseModel, NldBaseModelManager
from nld.pydantic.field_utils import TS_INSERTED_AT, TS_UPDATED_AT
from nld.utils.sqlglot import (
    identifier_list,
    literal_value,
    quote_identifier,
    quote_table,
)
from nld.utils.sqlglot.utils import POSTGRES_DIALECT

from .structure_mapper import (
    PostgreSQLPydanticStructureMapper,
)


def _is_collection_field_annotation(annotation: Any) -> bool:
    """Return True when ``annotation`` resolves to a dict / list type.

    Walks ``T | None`` unions and generics so e.g.
    ``dict[str, Any] | None`` and ``list[Foo]`` both match.
    """
    origin = typing.get_origin(annotation)
    if origin is types.UnionType or origin is typing.Union:
        return any(
            _is_collection_field_annotation(arg)
            for arg in typing.get_args(annotation)
            if arg is not type(None)
        )
    if origin in (dict, list):
        return True
    return annotation in (dict, list)


def _coerce_row_for_model(
    model_class: type[NldBaseModel],
    row: dict[str, Any],
) -> dict[str, Any]:
    """Bridge raw cursor values to what the Pydantic model expects.

    Handles the case where a JSON-typed column is stored as ``text``
    (or where the psycopg2 type adapter for ``json`` / ``jsonb`` did
    not fire): if the target field accepts ``dict`` / ``list``, parse a
    string value through ``json.loads`` so Pydantic validation sees the
    structured value the field expects. Empty strings are normalised to
    empty containers; malformed strings are passed through unchanged so
    Pydantic can surface the underlying error.
    """
    for field_name, field_info in model_class.model_fields.items():
        if field_name not in row:
            continue
        value = row[field_name]
        if not isinstance(value, str):
            continue
        if not _is_collection_field_annotation(field_info.annotation):
            continue
        if value == "":
            row[field_name] = (
                {} if dict in _origin_classes(field_info.annotation) else []
            )
            continue
        try:
            row[field_name] = json.loads(value)
        except json.JSONDecodeError:
            # Leave as-is and let Pydantic raise with the original
            # ``input_value`` so the operator sees the unparseable text.
            pass
    return row


def _origin_classes(annotation: Any) -> set[type]:
    """Collect concrete container origins from a (possibly union) annotation."""
    origin = typing.get_origin(annotation)
    if origin is types.UnionType or origin is typing.Union:
        result: set[type] = set()
        for arg in typing.get_args(annotation):
            if arg is type(None):
                continue
            result.update(_origin_classes(arg))
        return result
    if origin in (dict, list):
        return {origin}
    if annotation in (dict, list):
        return {annotation}
    return set()


if TYPE_CHECKING:
    from nld.structure import Structure


class NldBaseModelPostgreSQLManager(NldBaseModelManager):
    """
    Manages insertion and update operations for Pydantic models on PostgreSQL.

    This class provides methods to persist Pydantic model instances to a
    PostgreSQL database using psycopg2 connections. It handles automatic type
    mapping, table operations, and supports both insert and upsert operations.

    When track_timestamps is enabled, two database-only columns are managed
    automatically:
    - ts_inserted_at: set to CURRENT_TIMESTAMP on first insert, never updated.
    - ts_updated_at: set to CURRENT_TIMESTAMP on every insert or update.
    """

    def __init__(self, connector: Psycopg2SQLConnector):
        """Initialize the manager with a PostgreSQL connector."""
        self.connector = connector
        self.structure_mapper = PostgreSQLPydanticStructureMapper()

    def _prepare_value(self, value: Any) -> Any:
        """
        Prepare a value for insertion into PostgreSQL.

        Delegates to the PostgreSQL type mapper for proper value conversion.

        Args:
            value: Value to prepare

        Returns:
            PostgreSQL-compatible value
        """
        return self.structure_mapper.prepare_value_for_target(value)

    def _create_functional_key_index(
        self,
        structure: "Structure",
        table_name: str,
        table_path: str,
        use_functional_key_as_primary: bool,
    ) -> None:
        """Create indexes for functional keys when not used as primary key."""
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
                use_constraint=True,
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
        """Insert a Pydantic model instance into a PostgreSQL table."""
        data = model.model_dump(exclude=exclude_fields)
        columns = list(data.keys())
        value_strings = [
            literal_value(
                self._prepare_value(data[col]),
                dialect=POSTGRES_DIALECT,
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
            dialect=POSTGRES_DIALECT,
        )
        cols = identifier_list(
            columns,
            dialect=POSTGRES_DIALECT,
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
        """Update a Pydantic model instance in a PostgreSQL table."""
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
            f"{quote_identifier(field, dialect=POSTGRES_DIALECT)} = "
            f"{
                literal_value(
                    self._prepare_value(data[field]),
                    dialect=POSTGRES_DIALECT,
                )
            }"
            for field in update_fields
        ]

        if track_timestamps:
            quoted_ts = quote_identifier(
                TS_UPDATED_AT,
                dialect=POSTGRES_DIALECT,
            )
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
            dialect=POSTGRES_DIALECT,
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
        """
        Insert or update a Pydantic model in PostgreSQL using ON CONFLICT.

        When track_timestamps is enabled, ts_inserted_at is set on insert
        only (excluded from the ON CONFLICT UPDATE clause) and ts_updated_at
        is set on both insert and update.

        Args:
            model: Pydantic model instance to upsert
            schema_name: PostgreSQL schema name
            table_name: Table name
            conflict_fields: Fields to use in ON CONFLICT clause. If None, uses
                             primary key fields from the model structure.
            commit: Whether to commit the transaction
            exclude_fields: Optional set of field names to exclude from persistence
            track_timestamps: If True, manages ts_inserted_at and ts_updated_at

        Raises:
            ValueError: If model has no primary key and conflict_fields not
                        provided, or if no fields to update after excluding
                        conflict fields
        """
        self.bulk_upsert_models(
            models=[model],
            schema_name=schema_name,
            table_name=table_name,
            conflict_fields=conflict_fields,
            commit=commit,
            exclude_fields=exclude_fields,
            track_timestamps=track_timestamps,
        )

    def bulk_upsert_models(
        self,
        models: Sequence[NldBaseModel],
        schema_name: str,
        table_name: str,
        conflict_fields: list[str] | None = None,
        commit: bool = True,
        exclude_fields: set[str] | None = None,
        track_timestamps: bool = False,
        batch_size: int = 1000,
    ) -> None:
        """Upsert a list of Pydantic models using batched multi-row INSERTs.

        Models are split into chunks of ``batch_size`` and each chunk is
        executed as a single INSERT ... VALUES (...), (...), ... ON CONFLICT
        statement, which is dramatically faster than per-row upserts when
        many rows must be persisted.
        """
        if not models:
            return

        model_class = models[0].__class__
        structure = self.structure_mapper.get_structure(model_class)

        if conflict_fields is None:
            if not structure.has_primary_key():
                raise ValueError(
                    f"The base model {model_class.__name__} has no primary "
                    "key and conflict_fields parameter was not provided."
                )
            conflict_fields = [
                field.name for field in structure.get_primary_key_fields()
            ]

        data_columns = list(
            models[0].model_dump(exclude=exclude_fields).keys(),
        )
        columns = list(data_columns)
        if track_timestamps:
            columns.append(TS_INSERTED_AT)
            columns.append(TS_UPDATED_AT)

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
            f"{field} = EXCLUDED.{field}"
            for field in update_fields
            if field not in timestamp_columns
        ]
        if track_timestamps:
            quoted_ts = quote_identifier(
                TS_UPDATED_AT,
                dialect=POSTGRES_DIALECT,
            )
            update_parts.append(f"{quoted_ts} = CURRENT_TIMESTAMP")
        update_set = ", ".join(update_parts)

        data_cols_for_comparison = [
            field for field in update_fields if field not in timestamp_columns
        ]
        if data_cols_for_comparison:
            where_parts = [
                f'"{table_name}"."{col}" IS DISTINCT FROM EXCLUDED."{col}"'
                for col in data_cols_for_comparison
            ]
            change_where = f" WHERE ({' OR '.join(where_parts)})"
        else:
            change_where = ""

        table_ref = quote_table(
            schema=schema_name,
            table=table_name,
            dialect=POSTGRES_DIALECT,
        )
        cols = identifier_list(
            columns,
            dialect=POSTGRES_DIALECT,
        )
        conflict_cols = identifier_list(
            conflict_fields,
            dialect=POSTGRES_DIALECT,
        )

        for batch_start in range(0, len(models), batch_size):
            batch = models[batch_start : batch_start + batch_size]
            row_strings: list[str] = []
            for model in batch:
                data = model.model_dump(exclude=exclude_fields)
                value_strings = [
                    literal_value(
                        self._prepare_value(data[col]),
                        dialect=POSTGRES_DIALECT,
                    )
                    for col in data_columns
                ]
                if track_timestamps:
                    value_strings.append("CURRENT_TIMESTAMP")
                    value_strings.append("CURRENT_TIMESTAMP")
                row_strings.append(f"({', '.join(value_strings)})")

            vals = ", ".join(row_strings)
            upsert_query = (
                f"INSERT INTO {table_ref} ({cols}) VALUES {vals} "
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
        """
        Read a single Pydantic model instance from a PostgreSQL table.

        Args:
            model_class: Pydantic model class to instantiate from results
            schema_name: PostgreSQL schema name
            table_name: Table name to query
            where_conditions: Optional dictionary of field:value pairs for WHERE
                              clause filtering. Multiple conditions are combined
                              with AND.
            order_by: Optional list of field names to order by (e.g., ["name",
                      "-created_at"] where "-" prefix means DESC). Used to
                      determine which record to return when multiple match.
            exclude_fields: Optional set of field names to exclude from the
                            SELECT query. Excluded fields will have their
                            default values in the returned model.

        Returns:
            Single model instance populated from database row, or None if no
            matching record found

        Example:
            ```python
            user = manager.read_model(
                model_class=User,
                schema_name="public",
                table_name="users",
                where_conditions={"id": 1},
            )
            ```
        """
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
        """
        Read multiple Pydantic model instances from a PostgreSQL table.

        Args:
            model_class: Pydantic model class to instantiate from results
            schema_name: PostgreSQL schema name
            table_name: Table name to query
            where_conditions: Optional dictionary of field:value pairs for WHERE
                              clause filtering. Multiple conditions are combined
                              with AND.
            limit: Optional maximum number of rows to return
            order_by: Optional list of field names to order by (e.g., ["name",
                      "-created_at"] where "-" prefix means DESC)
            exclude_fields: Optional set of field names to exclude from the
                            SELECT query. Excluded fields will have their
                            default values in the returned models.

        Returns:
            List of model instances populated from database rows

        Example:
            ```python
            users = manager.read_models(
                model_class=User,
                schema_name="public",
                table_name="users",
                where_conditions={"is_active": True},
                order_by=["name"],
                limit=10,
            )
            ```
        """
        table_ref = quote_table(
            schema=schema_name,
            table=table_name,
            dialect=POSTGRES_DIALECT,
        )

        if exclude_fields:
            all_field_names = list(model_class.model_fields.keys())
            selected_columns = [
                field_name
                for field_name in all_field_names
                if field_name not in exclude_fields
            ]
            cols = identifier_list(
                selected_columns,
                dialect=POSTGRES_DIALECT,
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
                    quoted = quote_identifier(
                        field[1:],
                        dialect=POSTGRES_DIALECT,
                    )
                    order_parts.append(f"{quoted} DESC")
                else:
                    quoted = quote_identifier(
                        field,
                        dialect=POSTGRES_DIALECT,
                    )
                    order_parts.append(f"{quoted} ASC")
            query_str += f" ORDER BY {', '.join(order_parts)}"

        if limit is not None:
            query_str += f" LIMIT {literal_value(limit, dialect=POSTGRES_DIALECT)}"

        result = self.connector.execute_query(query_str)

        # Use the raw records helper rather than the pandas DataFrame view:
        # pandas would promote NULLs in numeric columns to NaN (which
        # Pydantic rejects on ``int | None`` fields) and complicate type
        # preservation for JSONB columns.
        # ``_coerce_row_for_model`` then turns string values into dicts /
        # lists for fields whose target type is a collection, so JSON
        # data persisted in ``text`` / ``json`` / ``jsonb`` columns all
        # validate the same way regardless of the underlying column type.
        return [
            model_class.model_validate(_coerce_row_for_model(model_class, row))
            for row in result.get_output_data_as_records()
        ]
