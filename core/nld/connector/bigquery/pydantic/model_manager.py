import json
from functools import cache
from typing import TYPE_CHECKING, Any, get_origin

from sqlglot import exp

from nld.pydantic import NldBaseModel, NldBaseModelManager
from nld.pydantic.field_utils import TS_INSERTED_AT, TS_UPDATED_AT
from nld.utils.sqlglot import (
    literal_value,
)

from .structure_mapper import BigQueryPydanticStructureMapper

if TYPE_CHECKING:
    from nld.connector.bigquery.bigquery_connector import BigQueryConnector

BIGQUERY_DIALECT = "bigquery"


def _bq_ident(name: str) -> str:
    """Backtick-quote a BigQuery identifier.

    BigQuery identifiers must be backtick-quoted when they contain
    hyphens (common in project IDs like ``my-project-id``) or collide
    with reserved words (``GROUP``, ``ORDER``, ``WINDOW``, ...).
    BigQuery does not permit backtick characters inside quoted
    identifiers at all, so we reject them up-front rather than
    producing invalid SQL — matching ``BigQueryConnector._quote_ident``.
    """
    if "`" in name:
        raise ValueError(f"BigQuery identifiers cannot contain backticks: {name!r}")
    return f"`{name}`"


def _bq_table_ref(schema: str, table: str) -> str:
    """Build a backtick-quoted BigQuery table reference (dataset.table)."""
    return f"{_bq_ident(schema)}.{_bq_ident(table)}"


def _bq_cols(columns: list[str]) -> str:
    """Build a comma-separated backtick-quoted column list."""
    return ", ".join(_bq_ident(col) for col in columns)


@cache
def _resolve_bq_field_types(model_class: type[NldBaseModel]) -> dict[str, str]:
    """Return the BigQuery data type for each field of a pydantic model.

    Cached at module level keyed on ``model_class`` so that repeated
    metadata writes for the same row class do not re-walk the pydantic
    field annotations.
    """
    structure = BigQueryPydanticStructureMapper.get_structure(model_class)
    return {name: field.data_type for name, field in structure.fields.items()}


def _get_json_serialized_fields(model_class: type[NldBaseModel]) -> list[str]:
    """Return field names that are stored as JSON strings in BigQuery.

    Dict, list, and NldBaseModel fields are serialized to JSON STRING on
    write (see BigQueryPydanticStructureMapper.prepare_value_for_target).
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


class NldBaseModelBigQueryManager(NldBaseModelManager):
    """Manages Pydantic model persistence operations on BigQuery.

    Provides methods to create tables, insert, update, upsert, and read
    Pydantic model instances using BigQuery SQL syntax.

    When track_timestamps is enabled, two database-only columns are managed
    automatically:
    - ts_inserted_at: set to CURRENT_TIMESTAMP() on first insert, never updated.
    - ts_updated_at: set to CURRENT_TIMESTAMP() on every insert or update.

    Transaction semantics — BigQuery has no batching transaction around
    a sequence of DML statements at the client-library level: every
    ``execute_query`` call is an independent job that commits on
    success. The ``commit`` parameter on ``insert_model`` /
    ``update_model`` / ``upsert_model`` is therefore accepted for API
    parity with the Postgres / Snowflake managers but is a NO-OP on
    BigQuery. Callers chaining multiple writes (e.g. state-table
    upserts followed by history inserts) must treat intermediate
    failures as partial state and handle recovery explicitly; there
    is no rollback.
    """

    # ``TIMESTAMPTZ`` is the sqlglot-canonical name for a TZ-aware
    # timestamp; sqlglot's bigquery dialect renders it as ``TIMESTAMP``
    # (BigQuery's TZ-aware type). ``TIMESTAMP`` (the unqualified ANSI
    # name) would be rendered as BigQuery ``DATETIME`` instead.
    _TIMESTAMP_COLUMN_TYPE: str = "TIMESTAMPTZ"
    _TIMESTAMP_DEFAULT: str = "CURRENT_TIMESTAMP()"

    def __init__(self, connector: "BigQueryConnector") -> None:
        """Initialize the manager with a BigQuery connector."""
        self.connector = connector
        self.structure_mapper = BigQueryPydanticStructureMapper()

    def _prepare_value(self, value: Any) -> Any:
        """Prepare a value for insertion into BigQuery."""
        return self.structure_mapper.prepare_value_for_target(value)

    def _to_sql_literal(self, value: Any, bq_type: str | None = None) -> str:
        """Convert a prepared value to a SQL literal for BigQuery.

        BigQuery treats unqualified ``NULL`` as ``INT64`` when used in
        ``SELECT NULL AS col``, which then breaks ``MERGE`` source-to-
        target assignments on non-INT64 columns. When the caller knows
        the target type (in sqlglot canonical form) and the value is
        None, we emit ``CAST(NULL AS <bq_type>)`` after rendering the
        type via sqlglot so canonical names like ``TIMESTAMPTZ`` are
        translated to BigQuery's native ``TIMESTAMP``.
        """
        prepared = self._prepare_value(value)
        if prepared is None and bq_type is not None:
            # ``dialect=BIGQUERY_DIALECT`` on *build* is required so
            # BQ-native names like ``INT64`` / ``FLOAT64`` / ``BOOL``
            # parse reliably — sqlglot's ``DataType.build`` is dialect
            # sensitive and would otherwise only understand ANSI
            # aliases. Matches ``BigQueryConnector._bq_literal``.
            rendered_type = exp.DataType.build(bq_type, dialect=BIGQUERY_DIALECT).sql(
                dialect=BIGQUERY_DIALECT
            )
            return f"CAST(NULL AS {rendered_type})"
        return literal_value(prepared, dialect=BIGQUERY_DIALECT)

    def _get_field_bq_types(
        self,
        model_class: type[NldBaseModel],
    ) -> dict[str, str]:
        """Return the BigQuery data type for each field of the model.

        Cached per ``model_class`` because the structure derives only
        from the pydantic class definition (not from instance values),
        and metadata writes call this on every insert/upsert.
        """
        return _resolve_bq_field_types(model_class)

    def insert_model(
        self,
        model: NldBaseModel,
        schema_name: str,
        table_name: str,
        commit: bool = True,
        exclude_fields: set[str] | None = None,
        track_timestamps: bool = False,
    ) -> None:
        """Insert a Pydantic model instance into a BigQuery table."""
        data = model.model_dump(exclude=exclude_fields)
        columns = list(data.keys())
        bq_types = self._get_field_bq_types(model.__class__)
        value_strings = [
            self._to_sql_literal(data[col], bq_type=bq_types.get(col))
            for col in columns
        ]

        if track_timestamps:
            columns.append(TS_INSERTED_AT)
            value_strings.append("CURRENT_TIMESTAMP()")
            columns.append(TS_UPDATED_AT)
            value_strings.append("CURRENT_TIMESTAMP()")

        table_ref = _bq_table_ref(schema_name, table_name)
        cols = _bq_cols(columns)
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
        """Update a Pydantic model instance in a BigQuery table."""
        structure = self.structure_mapper.get_structure(model.__class__)
        if not structure.has_primary_key():
            raise ValueError(
                f"The base model {model.__class__.__name__} has no primary "
                "key and thus cannot be updated."
            )
        where_fields = [field.name for field in structure.get_primary_key_fields()]
        if exclude_fields and set(where_fields) & set(exclude_fields):
            raise ValueError(
                f"exclude_fields cannot contain primary key fields "
                f"{sorted(set(where_fields) & set(exclude_fields))}: "
                f"they are required for the UPDATE WHERE clause."
            )
        data = model.model_dump(exclude=exclude_fields)
        update_fields = [f for f in data.keys() if f not in where_fields]

        if not update_fields:
            raise ValueError("No fields to update after excluding where_fields")

        bq_types = self._get_field_bq_types(model.__class__)
        set_parts = [
            f"{_bq_ident(field)} = "
            f"{self._to_sql_literal(data[field], bq_type=bq_types.get(field))}"
            for field in update_fields
        ]

        if track_timestamps:
            set_parts.append(f"{_bq_ident(TS_UPDATED_AT)} = CURRENT_TIMESTAMP()")

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

        table_ref = _bq_table_ref(schema_name, table_name)
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
        """Upsert a Pydantic model as an atomic UPDATE + insert-if-absent.

        Emitted as a single multi-statement transaction script rather
        than a MERGE: a single-row MERGE needs a subquery source, which
        some BigQuery backends (notably emulators) restrict to plain
        table references, while the script form is portable and keeps
        the same semantics — the matched row is always rewritten and
        ``ts_inserted_at`` is preserved on update.

        Note on semantics — unlike ``BigQueryConnector.upsert_from_query``
        (which emits a ``WHEN MATCHED AND (change predicate)`` to skip
        no-op updates), this method always rewrites the matched row.
        That is intentional: the pydantic manager is used for state /
        execution-tracking tables where every upsert is itself a
        meaningful state transition, and callers rely on
        ``ts_updated_at`` advancing on every touch. Flow-level bulk
        upserts that need no-op suppression should go through
        ``upsert_from_query`` instead.
        """
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

        if exclude_fields and set(conflict_fields) & set(exclude_fields):
            raise ValueError(
                f"exclude_fields cannot contain conflict_fields "
                f"{sorted(set(conflict_fields) & set(exclude_fields))}: "
                f"they are required for the MERGE ON clause."
            )

        data = model.model_dump(exclude=exclude_fields)
        columns = list(data.keys())
        bq_types = self._get_field_bq_types(model.__class__)
        value_strings = [
            self._to_sql_literal(data[col], bq_type=bq_types.get(col))
            for col in columns
        ]

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

        table_ref = _bq_table_ref(schema_name, table_name)
        literal_by_column = dict(zip(columns, value_strings, strict=True))

        where_clause = " AND ".join(
            f"{_bq_ident(cf)} = {literal_by_column[cf]}" for cf in conflict_fields
        )

        timestamp_columns = (
            {TS_INSERTED_AT, TS_UPDATED_AT} if track_timestamps else set()
        )
        update_parts = [
            f"{_bq_ident(field)} = {literal_by_column[field]}"
            for field in update_fields
            if field not in timestamp_columns
        ]
        if track_timestamps:
            update_parts.append(f"{_bq_ident(TS_UPDATED_AT)} = CURRENT_TIMESTAMP()")
        update_set = ", ".join(update_parts)

        insert_cols = _bq_cols(columns)
        insert_vals = ", ".join(literal_by_column[col] for col in columns)

        upsert_script = (
            f"BEGIN TRANSACTION; "
            f"UPDATE {table_ref} SET {update_set} WHERE {where_clause}; "
            f"INSERT INTO {table_ref} ({insert_cols}) "
            f"SELECT {insert_vals} FROM (SELECT 1) AS _seed "
            f"WHERE NOT EXISTS ("
            f"SELECT 1 FROM {table_ref} WHERE {where_clause}"
            f"); "
            f"COMMIT TRANSACTION;"
        )
        self.connector.execute_query(upsert_script)

    def read_model(
        self,
        model_class: type[NldBaseModel],
        schema_name: str,
        table_name: str,
        where_conditions: dict[str, Any] | None = None,
        order_by: list[str] | None = None,
        exclude_fields: set[str] | None = None,
    ) -> NldBaseModel | None:
        """Read a single Pydantic model instance from a BigQuery table."""
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
        """Read multiple Pydantic model instances from a BigQuery table."""
        table_ref = _bq_table_ref(schema_name, table_name)

        if exclude_fields:
            all_field_names = list(model_class.model_fields.keys())
            selected_columns = [
                field_name
                for field_name in all_field_names
                if field_name not in exclude_fields
            ]
            cols = _bq_cols(selected_columns)
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
                    order_parts.append(f"{_bq_ident(field[1:])} DESC")
                else:
                    order_parts.append(f"{_bq_ident(field)} ASC")
            query_str += f" ORDER BY {', '.join(order_parts)}"

        if limit is not None:
            query_str += f" LIMIT {literal_value(limit, dialect=BIGQUERY_DIALECT)}"

        result = self.connector.execute_query(query_str)
        if result.failed():
            # Surface the underlying error instead of masking it as
            # "no rows" — a permission error or bad SQL must not be
            # indistinguishable from an empty result set.
            raise RuntimeError(
                f"read_models query failed for {model_class.__name__}: "
                f"{result.get_error_message()}"
            )
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
