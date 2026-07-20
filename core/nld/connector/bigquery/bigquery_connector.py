from __future__ import annotations

from typing import TYPE_CHECKING, Any

from google.api_core import exceptions as google_exceptions
from google.cloud import bigquery
from sqlglot import exp

from nld.connector.base import (
    ConnectorDefinition,
    ConnectorDeployCapabilities,
    QueryExecResult,
    QueryExecResultStatus,
    QueryExecutionException,
    QueryOutputType,
    QueryWrapper,
    SQLDataConnector,
)
from nld.connector.bigquery.bigquery_connection import BigQueryConnectionWrapper
from nld.connector.bigquery.query_wrapper import BigQueryQueryWrapper
from nld.logging.events import CSVFileWriteSuccessful
from nld.structure import Structure
from nld.utils.datetime_util import get_current_datetime
from nld.utils.sqlglot import (
    identifier_list,
    literal_list,
    literal_value,
    quote_table,
)
from nld.utils.sqlglot.base_ddl import BaseSqlglotDDLBuilder
from nld.utils.sqlglot.base_dml import BaseSqlglotDMLBuilder

BIGQUERY_DIALECT = "bigquery"


if TYPE_CHECKING:
    from nld.connector.bigquery.pydantic import NldBaseModelBigQueryManager
    from nld.connector.bigquery.service.data_profiler import (
        BigQueryDataProfiler,
    )
    from nld.connector.bigquery.service.structure_diff_ddl_statement_builder import (
        BigQueryStructureDiffDDLStatementBuilder,
    )
    from nld.connector.bigquery.service.structure_reader import (
        BigQueryStructureReader,
    )


class BigQueryConnector(SQLDataConnector[BigQueryConnectionWrapper]):
    """Connector class for Google BigQuery.

    Provides methods to execute queries and perform DDL/DML operations
    against BigQuery datasets using the google-cloud-bigquery client.
    """

    def __init__(self, connection_wrapper: BigQueryConnectionWrapper) -> None:
        super().__init__(connection_wrapper)

    @property
    def sqlglot_dialect(self) -> str:
        """The sqlglot dialect name for SQL rendering."""
        return "bigquery"

    def get_ddl_builder(self) -> BaseSqlglotDDLBuilder:
        """Return a BigQuery-specific DDL builder."""
        from nld.connector.bigquery.sqlglot import BigQuerySqlglotDDLBuilder

        return BigQuerySqlglotDDLBuilder()

    def get_dml_builder(self) -> BaseSqlglotDMLBuilder:
        """Return a BigQuery-specific DML builder."""
        from nld.connector.bigquery.sqlglot import BigQuerySqlglotDMLBuilder

        return BigQuerySqlglotDMLBuilder()

    def get_structure_diff_ddl_statement_builder(
        self,
    ) -> BigQueryStructureDiffDDLStatementBuilder:
        """Return a BigQuery DDL generator for structure deployment."""
        from nld.connector.bigquery.service import (
            BigQueryStructureDiffDDLStatementBuilder,
        )

        return BigQueryStructureDiffDDLStatementBuilder()

    def get_connector_definition(self) -> ConnectorDefinition:
        """Return the static engine facts of the BigQuery connector."""
        from nld.connector.bigquery.connector_definition import (
            BIGQUERY_CONNECTOR_DEFINITION,
        )

        return BIGQUERY_CONNECTOR_DEFINITION

    def get_deploy_capabilities(self) -> ConnectorDeployCapabilities:
        """Return the declared BigQuery structure deployment capabilities."""
        from nld.connector.bigquery.service import (
            BIGQUERY_DEPLOY_CAPABILITIES,
        )

        return BIGQUERY_DEPLOY_CAPABILITIES

    @property
    def client(self) -> bigquery.Client:
        """Return the active BigQuery client."""
        if self.connection_wrapper.connection is None:
            raise ValueError(
                f"No connection available on "
                f"BigQuery connector {self.connection_wrapper.name}"
            )
        return self.connection_wrapper.connection

    def get_active_project(self) -> str:
        """Return the active GCP project ID."""
        return self.connection_wrapper.get_active_project()

    def _query_retry_kwargs(self) -> dict[str, Any]:
        """Query retry policy adapted to the endpoint.

        Emulators classify every failure as ``jobInternalError``, which
        the client's default job retry treats as transient and retries
        for up to ten minutes — a plain SQL error would block instead
        of failing fast. Against an emulator endpoint, disable it.
        """
        if self.connection_wrapper.credentials.api_endpoint is not None:
            return {"job_retry": None}
        return {}

    def get_active_dataset(self) -> str | None:
        """Return the active default dataset ID."""
        return self.connection_wrapper.get_active_dataset()

    def get_active_schema(self) -> str | None:
        """Return the active schema (alias for active dataset in BigQuery).

        BigQuery datasets play the role of schemas in the connector
        abstraction shared with other SQL backends, so ``get_active_schema``
        delegates to ``get_active_dataset``.
        """
        return self.get_active_dataset()

    def get_structure_reader(self) -> BigQueryStructureReader:
        """Return a BigQuery structure reader for this connector."""
        from nld.connector.bigquery.service.structure_reader import (
            BigQueryStructureReader,
        )

        return BigQueryStructureReader(self)

    def get_data_profiler(self) -> BigQueryDataProfiler:
        """Return a BigQuery data profiler for this connector."""
        from nld.connector.bigquery.service.data_profiler import (
            BigQueryDataProfiler,
        )

        return BigQueryDataProfiler(self)

    def get_model_manager(self) -> NldBaseModelBigQueryManager:
        """Return a BigQuery pydantic model manager."""
        from nld.connector.bigquery.pydantic import NldBaseModelBigQueryManager

        return NldBaseModelBigQueryManager(connector=self)

    def log_execution_error(self, error: Exception) -> None:  # type: ignore[override]
        """Log execution errors from the BigQuery client."""
        self.log_error(f"BigQuery execution error: {error}")

    @staticmethod
    def clean_object_path(object_path: str) -> str:
        """Cleans the object path by checking specification compliance."""
        return object_path

    @staticmethod
    def _quote_ident(name: str) -> str:
        """Backtick-quote a single BigQuery identifier.

        Required for identifiers containing hyphens (BQ project IDs) or
        reserved words (``GROUP``, ``ORDER``, ``WINDOW``, ...). BigQuery
        does not permit backtick characters inside quoted identifiers,
        so any embedded backtick is rejected up-front instead of
        producing invalid SQL.
        """
        if "`" in name:
            raise ValueError(f"BigQuery identifiers cannot contain backticks: {name!r}")
        return exp.to_identifier(name, quoted=True).sql(dialect=BIGQUERY_DIALECT)

    def _prepare_query_wrapper(
        self,
        query: str | QueryWrapper,
    ) -> BigQueryQueryWrapper:
        """Convert a query string or QueryWrapper to a BigQueryQueryWrapper."""
        if isinstance(query, BigQueryQueryWrapper):
            return query
        if isinstance(query, QueryWrapper):
            return BigQueryQueryWrapper(
                query=query.query,
                interpreted_query=query.interpreted_query,
                name=query.name,
                params=query.params,
                runtime_exception_message=query.runtime_exception_message,
            )
        return BigQueryQueryWrapper(query=query)

    def execute_query(self, query: str | QueryWrapper) -> QueryExecResult:
        """Execute a query using the BigQuery client.

        Args:
            query: The query wrapper or raw SQL string.

        Returns:
            The result of the query execution.
        """
        query_wrapper = self._prepare_query_wrapper(query)
        start_tst = get_current_datetime()
        query_wrapper.update_interpreted_query()
        self.log_debug(
            f"Query to be executed: {query_wrapper.interpreted_query}",
        )
        expected_output = query_wrapper.get_expected_output_type()
        resolved_operation_type = query_wrapper.operation_type

        try:
            query_job = self.client.query(
                query_wrapper.get_interpreted_query(),
                **self._query_retry_kwargs(),
            )
            result_iterator = query_job.result()

            message = None
            results = None
            row_count = None
            structure = None

            if expected_output == QueryOutputType.DATASET:
                results = [dict(row) for row in result_iterator]
                # ``query_job.schema`` is only populated for queries that
                # reference a physical schema; computed/aggregate SELECTs
                # leave it as ``None``. The RowIterator returned by
                # ``result()`` always carries the resolved schema, so we
                # prefer it and fall back to ``query_job.schema`` only
                # when the iterator did not expose one.
                schema = result_iterator.schema or query_job.schema
                structure = self._build_structure_from_schema(
                    schema,
                    row_count=len(results),
                )
            elif expected_output == QueryOutputType.ROW_COUNT:
                row_count = query_job.num_dml_affected_rows or 0
            else:
                message = (
                    f"{resolved_operation_type.value} statement executed successfully."
                    if resolved_operation_type is not None
                    else "Statement executed successfully."
                )

            return QueryExecResult(
                query_name=query_wrapper.name,
                exec_status=QueryExecResultStatus.SUCCESS,
                query=query_wrapper.get_interpreted_query(),
                query_id=query_job.job_id,
                output_structure=structure,
                start_tst=start_tst,
                end_tst=get_current_datetime(),
                message=message,
                operation_type=resolved_operation_type,
                row_count=row_count,
                result_data=results,
            )
        except (
            google_exceptions.GoogleAPICallError,
            google_exceptions.RetryError,
            ValueError,
        ) as ex:
            # Wrap client-side errors (auth, network retry exhaustion,
            # malformed params) the same way as server-side errors so
            # the QueryExecResult wrapping stays consistent with the
            # other connectors instead of leaking raw exceptions.
            self.log_execution_error(ex)
            query_wrapper.raise_runtime_exception()
            return QueryExecResult(
                query_name=query_wrapper.name,
                exec_status=QueryExecResultStatus.ERROR,
                query=query_wrapper.get_interpreted_query(),
                query_id=None,
                output_structure=None,
                start_tst=start_tst,
                end_tst=get_current_datetime(),
                operation_type=resolved_operation_type,
                result_data=[str(ex)],
            )

    def export_query_to_csv(
        self,
        query: str | QueryWrapper,
        output_file_path: str,
        delimiter: str = ",",
        include_header: bool = True,
        encoding: str = "utf-8",
    ) -> int:
        """Export a SELECT result to CSV via the BigQuery client.

        The query result is materialized with the client's native
        ``to_dataframe`` before being written to the target CSV file.
        """
        self.assert_select_query(query)
        query_text = query.query if isinstance(query, QueryWrapper) else query
        try:
            query_job = self.client.query(query_text)
            data_frame = query_job.result().to_dataframe()
        except (
            google_exceptions.GoogleAPICallError,
            google_exceptions.RetryError,
            ValueError,
        ) as error:
            self.log_execution_error(error)
            raise QueryExecutionException(error_message=str(error)) from error
        data_frame.to_csv(
            output_file_path,
            sep=delimiter,
            header=include_header,
            index=False,
            encoding=encoding,
        )
        self.log_event(
            CSVFileWriteSuccessful(
                object_type_name="QueryResult",
                file_path=output_file_path,
            ),
        )
        return len(data_frame)

    def _build_structure_from_schema(
        self,
        schema: list[bigquery.SchemaField] | None,
        row_count: int = 0,
    ) -> Structure | None:
        """Build a Structure from BigQuery result schema fields."""
        if not schema:
            return None

        from nld.structure import Field

        fields: dict[str, Field] = {}
        for field in schema:
            # Preserve the BigQuery ``mode`` (REPEATED, NULLABLE,
            # REQUIRED) and STRUCT field listing in the rendered type
            # string so callers can tell arrays and structs apart from
            # scalars — ``field_type`` alone only carries the base
            # name ("RECORD", "STRING") and loses this information.
            data_type = field.field_type
            if field.field_type == "RECORD" and field.fields:
                inner = ", ".join(f"{f.name} {f.field_type}" for f in field.fields)
                data_type = f"STRUCT<{inner}>"
            if field.mode == "REPEATED":
                data_type = f"ARRAY<{data_type}>"
            fields[field.name] = Field(
                name=field.name,
                data_type=data_type,
            )

        return Structure(
            name="query_result",
            structure_type="QUERY_RESULT",
            connector_type="bigquery",
            fields=fields,
        )

    # DDL operations

    def truncate_table(self, table_path: str, **kwargs: Any) -> QueryExecResult:
        """Truncate a BigQuery table using the native TRUNCATE TABLE DDL.

        BigQuery has supported ``TRUNCATE TABLE`` since 2021. Prefer it
        over ``DELETE FROM ... WHERE true`` because TRUNCATE is a
        metadata-only operation (free, instantaneous, and not subject
        to the partition-modification quota), whereas DELETE is billed
        DML that scans and rewrites every row.
        """
        table_path = self.clean_object_path(table_path)
        dataset, table_name = self._split_object_path(table_path)
        table_ref = quote_table(
            schema=dataset,
            table=table_name,
            dialect=BIGQUERY_DIALECT,
        )
        return self.execute_query(
            query=QueryWrapper(
                query=f"TRUNCATE TABLE {table_ref}",
                name=table_path,
            ),
        )

    def drop_table(
        self,
        table_path: str,
        if_exists: bool = False,
        **kwargs: Any,
    ) -> QueryExecResult:
        table_path = self.clean_object_path(table_path)
        dataset, table_name = self._split_object_path(table_path)
        return self.execute_query(
            query=QueryWrapper(
                query=self.get_ddl_builder().build_drop_table(
                    schema=dataset,
                    table=table_name,
                    if_exists=if_exists,
                ),
                name=table_path,
            ),
        )

    def create_table(  # type: ignore[override]
        self,
        table_path: str,
        structure: Structure,
        table_exists: str = "skip",
        override_primary_key_fields: list[str] | None = None,
        **kwargs: Any,
    ) -> QueryExecResult | None:
        if table_exists not in ("skip", "replace", "fail"):
            raise ValueError(
                f"table_exists must be 'skip', 'replace', or 'fail', got {table_exists}"
            )

        object_exists = self.does_object_exist(table_path)

        if object_exists:
            if table_exists == "skip":
                return None
            elif table_exists == "replace":
                self.drop_table(
                    table_path,
                    if_exists=True,
                )
                self.log_info(f"Table {table_path} dropped.")
            elif table_exists == "fail":
                raise ValueError(f"Table {table_path} already exists")

        table_path = self.clean_object_path(table_path)
        dataset, table_name = self._split_object_path(table_path)

        # Honor the MANDATORY characterisation from the structure
        # definition so the generated DDL sets NOT NULL consistently
        # with what ``BigQueryStructureDiffDDLStatementBuilder`` would emit,
        # and preserve length / precision on the type so declared
        # ``STRING(n)`` / ``NUMERIC(p, s)`` schemas are created
        # faithfully instead of being flattened to the base type.
        ddl_builder = self.get_ddl_builder()
        columns = [
            (
                field.name,
                ddl_builder.build_type_expression(
                    data_type=field.data_type,
                    length=field.length,
                    precision=field.precision,
                ),
                field.is_mandatory(),
            )
            for field in structure.fields.values()
        ]

        # ``override_primary_key_fields`` lets callers (e.g. the
        # base model manager when ``use_functional_key_as_primary`` is
        # set) force the functional key as the PRIMARY KEY instead of
        # whatever the structure declares. Without this, the override
        # was silently swallowed by ``**kwargs`` and functional keys
        # never became primary keys in BigQuery.
        if override_primary_key_fields is not None:
            primary_key_fields: list[str] | None = override_primary_key_fields
        elif structure.has_primary_key():
            primary_key_fields = [
                field.name for field in structure.get_primary_key_fields()
            ]
        else:
            primary_key_fields = None

        create_sql = self.get_ddl_builder().build_create_table(
            schema=dataset,
            table=table_name,
            columns=columns,
            primary_key_fields=primary_key_fields,
        )
        return self.execute_query(query=create_sql)

    def does_object_exist(self, object_path: str, **kwargs: Any) -> bool:
        """Check table existence through the tables API.

        The REST metadata API only needs ``bigquery.tables.get`` and
        works on any endpoint — ``INFORMATION_SCHEMA.TABLES`` is not
        even query-able while a dataset is still empty.
        """
        object_path = self.clean_object_path(object_path)
        dataset, table_name = self._split_object_path(object_path)
        try:
            self.client.get_table(f"{dataset}.{table_name}")
        except google_exceptions.NotFound:
            return False
        return True

    def does_schema_exist(self, schema: str, **kwargs: Any) -> bool:
        """Check dataset existence through the datasets API.

        The REST metadata API only needs ``bigquery.datasets.get`` and
        works on any endpoint (including emulators), unlike the
        ``__TABLES__`` metaview which requires at least one query-able
        table path.
        """
        try:
            self.client.get_dataset(schema)
        except google_exceptions.NotFound:
            return False
        return True

    def get_column_names(self, object_path: str, **kwargs: Any) -> list[str]:
        """Read column names through the tables API, in schema order."""
        object_path = self.clean_object_path(object_path)
        dataset, table_name = self._split_object_path(object_path)
        table = self.client.get_table(f"{dataset}.{table_name}")
        return [field.name for field in table.schema]

    # DML operations

    def insert_into(
        self,
        table_path: str,
        data: dict[str, Any],
        **kwargs: Any,
    ) -> QueryExecResult:
        table_path = self.clean_object_path(table_path)
        dataset, table_name = self._split_object_path(table_path)
        columns = list(data.keys())
        values = list(data.values())

        table_ref = quote_table(
            schema=dataset,
            table=table_name,
            dialect=BIGQUERY_DIALECT,
        )
        cols = identifier_list(
            columns,
            dialect=BIGQUERY_DIALECT,
        )
        vals = literal_list(
            values,
            dialect=BIGQUERY_DIALECT,
        )

        insert_query = f"INSERT INTO {table_ref} ({cols}) VALUES ({vals})"
        return self.execute_query(insert_query)

    def upsert_into(
        self,
        table_path: str,
        data: dict[str, Any],
        upsert_fields: list[str],
        column_types: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> QueryExecResult:
        """Upsert using BigQuery MERGE statement.

        BigQuery does not support INSERT ... ON CONFLICT. Instead,
        uses MERGE INTO ... USING ... WHEN MATCHED / WHEN NOT MATCHED.

        ``column_types`` (optional) lets the caller supply BigQuery
        types per column so that ``None`` values render as
        ``CAST(NULL AS <type>)`` in the MERGE source — BigQuery
        otherwise infers untyped ``NULL`` as ``INT64`` and fails the
        merge on non-INT64 columns. When absent, types are inferred
        from the non-None values in ``data`` and fall back to
        ``STRING`` for all-None columns.
        """
        table_path = self.clean_object_path(table_path)
        dataset, table_name = self._split_object_path(table_path)
        columns = list(data.keys())
        values = list(data.values())
        update_fields = [col for col in columns if col not in upsert_fields]

        # Resolve BQ types per column: explicit overrides first, then
        # inference from the single data row, finally ``STRING`` as a
        # safe default.
        types_map = dict(column_types or {})
        for col, val in data.items():
            if col not in types_map:
                inferred = self._infer_bq_type(val)
                types_map[col] = inferred or "STRING"

        if not update_fields:
            raise ValueError(
                "No fields to update after excluding upsert_fields",
            )

        table_ref = quote_table(
            schema=dataset,
            table=table_name,
            dialect=BIGQUERY_DIALECT,
        )

        # BigQuery's MERGE source must be a SELECT whose columns are
        # aliased per-expression (``SELECT v1 AS c1, v2 AS c2``). The
        # previous form ``SELECT <vals> AS (<cols>)`` is not valid BQ
        # syntax and always fails at parse time.
        source_select = ", ".join(
            f"{self._bq_literal(val, bq_type=types_map.get(col))} "
            f"AS {self._quote_ident(col)}"
            for col, val in zip(columns, values, strict=False)
        )

        on_conditions = " AND ".join(
            f"target.{self._quote_ident(col)} = source.{self._quote_ident(col)}"
            for col in upsert_fields
        )
        update_set = ", ".join(
            f"target.{self._quote_ident(col)} = source.{self._quote_ident(col)}"
            for col in update_fields
        )
        insert_cols = ", ".join(self._quote_ident(c) for c in columns)
        insert_vals = ", ".join(f"source.{self._quote_ident(c)}" for c in columns)

        merge_query = (
            f"MERGE INTO {table_ref} AS target "
            f"USING (SELECT {source_select}) AS source "
            f"ON {on_conditions} "
            f"WHEN MATCHED THEN UPDATE SET {update_set} "
            f"WHEN NOT MATCHED THEN INSERT ({insert_cols}) "
            f"VALUES ({insert_vals})"
        )
        return self.execute_query(
            query=QueryWrapper(
                query=merge_query,
                name=table_path,
            ),
        )

    def delete_from(
        self,
        table_path: str,
        where_conditions: dict[str, Any],
        **kwargs: Any,
    ) -> QueryExecResult:
        table_path = self.clean_object_path(table_path)
        dataset, table_name = self._split_object_path(table_path)

        dml_builder = self.get_dml_builder()
        conditions = [
            dml_builder.equality_clause(
                field=field,
                value=value,
            )
            for field, value in where_conditions.items()
        ]
        where = dml_builder.and_clause(conditions)

        table_ref = quote_table(
            schema=dataset,
            table=table_name,
            dialect=BIGQUERY_DIALECT,
        )
        delete_query = f"DELETE FROM {table_ref} WHERE {where}"
        return self.execute_query(delete_query)

    def insert_into_from_query(
        self,
        table_path: str,
        sql_query: str,
        column_list: list[str],
        **kwargs: Any,
    ) -> QueryExecResult:
        table_path = self.clean_object_path(table_path)
        dataset, table_name = self._split_object_path(table_path)
        table_ref = quote_table(
            schema=dataset,
            table=table_name,
            dialect=BIGQUERY_DIALECT,
        )
        cols = identifier_list(
            column_list,
            dialect=BIGQUERY_DIALECT,
        )
        insert_query = f"INSERT INTO {table_ref} ({cols}) {sql_query}"
        return self.execute_query(
            query=QueryWrapper(
                query=insert_query,
                name=table_path,
            ),
        )

    def upsert_from_query(
        self,
        table_path: str,
        sql_query: str,
        column_list: list[str],
        upsert_fields: list[str],
        exclude_from_update: list[str] | None = None,
        expression_overrides: dict[str, str] | None = None,
        exclude_from_match: list[str] | None = None,
        **kwargs: Any,
    ) -> QueryExecResult:
        """Upsert rows from a SELECT query using MERGE."""
        table_path = self.clean_object_path(table_path)
        dataset, table_name = self._split_object_path(table_path)
        excluded_set = set(exclude_from_update or [])
        overrides = expression_overrides or {}
        update_fields = [
            col
            for col in column_list
            if col not in upsert_fields and col not in excluded_set
        ]

        if not update_fields:
            raise ValueError(
                "No fields to update after excluding upsert_fields",
            )

        table_ref = quote_table(
            schema=dataset,
            table=table_name,
            dialect=BIGQUERY_DIALECT,
        )

        exclude_from_match_set = set(exclude_from_match or [])

        on_conditions = " AND ".join(
            f"target.{self._quote_ident(col)} = source.{self._quote_ident(col)}"
            for col in upsert_fields
        )
        set_parts: list[str] = []
        for col in update_fields:
            qcol = self._quote_ident(col)
            if col in overrides:
                # Caller-supplied expression — trusted raw SQL, not an
                # identifier, so no quoting applied to the RHS.
                set_parts.append(f"target.{qcol} = {overrides[col]}")
            else:
                set_parts.append(f"target.{qcol} = source.{qcol}")
        update_set = ", ".join(set_parts)
        insert_cols = ", ".join(self._quote_ident(c) for c in column_list)
        insert_vals = ", ".join(f"source.{self._quote_ident(c)}" for c in column_list)

        # Emit a change-detection predicate on WHEN MATCHED so that
        # no-op upserts do not rewrite unchanged rows — matching the
        # Snowflake/Postgres behavior. ``exclude_from_match`` lets the
        # caller drop timestamp/audit columns whose values change on
        # every run but don't count as "real" updates. BigQuery has no
        # ``IS DISTINCT FROM`` so we fall back to a null-safe ``!=``.
        data_cols_for_comparison = [
            c
            for c in update_fields
            if c not in overrides and c not in exclude_from_match_set
        ]
        if data_cols_for_comparison:
            change_conditions = " OR ".join(
                f"(target.{self._quote_ident(c)} != source.{self._quote_ident(c)}) "
                f"OR ((target.{self._quote_ident(c)} IS NULL) != "
                f"(source.{self._quote_ident(c)} IS NULL))"
                for c in data_cols_for_comparison
            )
            matched_clause = (
                f"WHEN MATCHED AND ({change_conditions}) THEN UPDATE SET {update_set} "
            )
        else:
            matched_clause = f"WHEN MATCHED THEN UPDATE SET {update_set} "

        merge_query = (
            f"MERGE INTO {table_ref} AS target "
            f"USING ({sql_query}) AS source "
            f"ON {on_conditions} "
            f"{matched_clause}"
            f"WHEN NOT MATCHED THEN INSERT ({insert_cols}) "
            f"VALUES ({insert_vals})"
        )
        return self.execute_query(
            query=QueryWrapper(
                query=merge_query,
                name=table_path,
            ),
        )

    def delete_from_query(
        self,
        table_path: str,
        sql_query: str,
        key_columns: list[str],
        **kwargs: Any,
    ) -> QueryExecResult:
        table_path = self.clean_object_path(table_path)
        dataset, table_name = self._split_object_path(table_path)

        table_ref = quote_table(
            schema=dataset,
            table=table_name,
            dialect=BIGQUERY_DIALECT,
        )

        # BigQuery does not support tuple ``(a, b) IN (subquery)`` with
        # multiple columns. Use a correlated ``EXISTS`` against the
        # subquery instead — semantically equivalent and BQ-compatible.
        join_conditions = " AND ".join(
            f"_subq.{self._quote_ident(col)} = {table_ref}.{self._quote_ident(col)}"
            for col in key_columns
        )
        delete_query = (
            f"DELETE FROM {table_ref} "
            f"WHERE EXISTS ("
            f"SELECT 1 FROM ({sql_query}) AS _subq "
            f"WHERE {join_conditions}"
            f")"
        )
        return self.execute_query(
            query=QueryWrapper(
                query=delete_query,
                name=table_path,
            ),
        )

    def _split_object_path(self, object_path: str) -> tuple[str, str]:
        """Split a qualified object path into dataset and object name.

        Supports the canonical NLD forms:
        - ``table`` — the active dataset is used.
        - ``dataset.table`` — dataset and table split on the dot.

        Fully-qualified ``project.dataset.table`` paths are rejected
        because a 2-tuple cannot faithfully represent a 3-part name:
        downstream ``quote_table(schema=..., table=...)`` would
        re-quote ``project.dataset`` as a single identifier with an
        embedded dot, producing invalid BigQuery SQL. The BigQuery
        project is carried on the connection credentials, so callers
        should pass ``dataset.table`` and let the client apply the
        project.
        """
        parts = object_path.split(".")
        if len(parts) >= 3:
            raise ValueError(
                f"Fully-qualified 3-part table paths are not supported "
                f"by the BigQuery connector; pass ``dataset.table`` and "
                f"let the credentials carry the project. Got: {object_path!r}"
            )
        if len(parts) == 2:
            return parts[0], parts[1]
        return self.get_active_dataset() or "default", object_path

    @staticmethod
    def _bq_literal(value: Any, bq_type: str | None = None) -> str:
        """Render a Python value as a BigQuery SQL literal.

        When ``value`` is ``None`` and ``bq_type`` is known, emits
        ``CAST(NULL AS <bq_type>)``. This is required because
        BigQuery infers untyped ``NULL`` in a ``SELECT NULL AS col``
        as ``INT64``, which then breaks MERGE source-to-target
        assignments on non-INT64 columns and fails any ``UNION ALL``
        source whose other branches are typed differently.
        """
        if value is None and bq_type is not None:
            # Parse the caller-supplied type with the BigQuery dialect
            # so BQ-native names (``INT64``, ``FLOAT64``, …) and ANSI
            # aliases (``TIMESTAMP`` → BQ TZ-aware ``TIMESTAMP``) are
            # both accepted, then render back in the same dialect.
            rendered_type = exp.DataType.build(bq_type, dialect=BIGQUERY_DIALECT).sql(
                dialect=BIGQUERY_DIALECT
            )
            return f"CAST(NULL AS {rendered_type})"
        rendered: str = literal_value(value, dialect=BIGQUERY_DIALECT)
        return rendered

    @staticmethod
    def _infer_bq_type(value: Any) -> str | None:
        """Infer a BigQuery type name from a single Python value.

        Used as a fallback when the caller has not supplied explicit
        column types for the raw connector DML paths. ``None`` yields
        ``None`` (the caller must look at another row).
        """
        from datetime import date, datetime
        from decimal import Decimal

        if value is None:
            return None
        if isinstance(value, bool):
            return "BOOL"
        if isinstance(value, int):
            return "INT64"
        if isinstance(value, float):
            return "FLOAT64"
        if isinstance(value, Decimal):
            return "NUMERIC"
        if isinstance(value, datetime):
            # ``TIMESTAMPTZ`` is the sqlglot-canonical name that the
            # bigquery dialect renders back to BQ's TZ-aware
            # ``TIMESTAMP``. Plain ``TIMESTAMP`` would become
            # ``DATETIME`` (no tz) — a different BQ type.
            return "TIMESTAMPTZ"
        if isinstance(value, date):
            return "DATE"
        if isinstance(value, bytes):
            return "BYTES"
        return "STRING"

    def bulk_insert_into(
        self,
        table_path: str,
        rows: list[tuple[Any, ...]],
        column_list: list[str],
        conflict_merge_fields: list[str] | None = None,
        batch_size: int = 1000,
        column_types: dict[str, str] | None = None,
    ) -> list[QueryExecResult]:
        """Insert rows in batches using multi-row INSERT statements.

        When ``conflict_merge_fields`` is provided, uses BigQuery's
        ``MERGE INTO`` for upsert semantics instead of plain INSERT.
        BigQuery's MERGE source clause must list typed columns, so we
        wrap the value tuples in a ``UNION ALL`` of typed SELECTs.

        ``column_types`` (optional) supplies BigQuery types per column
        so ``None`` values render as ``CAST(NULL AS <type>)`` — BigQuery
        otherwise infers untyped ``NULL`` as ``INT64``, which breaks
        the MERGE source whenever the actual column is a different
        type (e.g. STRING), and breaks the ``UNION ALL`` as soon as
        another branch provides a non-None value of the real type.
        When not supplied, types are inferred from the first non-None
        value seen per column across all rows, falling back to
        ``STRING`` for all-None columns.
        """
        table_path = self.clean_object_path(table_path)
        dataset, table_name = self._split_object_path(table_path)
        table_ref = quote_table(
            schema=dataset,
            table=table_name,
            dialect=BIGQUERY_DIALECT,
        )
        quoted_cols = ", ".join(self._quote_ident(c) for c in column_list)
        results: list[QueryExecResult] = []

        # Resolve BQ type per column: explicit overrides win, then
        # the first non-None value seen across all rows, else STRING.
        types_map = dict(column_types or {})
        for idx, col in enumerate(column_list):
            if col in types_map:
                continue
            inferred = next(
                (t for t in (self._infer_bq_type(row[idx]) for row in rows) if t),
                "STRING",
            )
            types_map[col] = inferred

        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            value_rows = ", ".join(
                f"({', '.join(self._bq_literal(v) for v in row)})" for row in batch
            )

            if conflict_merge_fields:
                on_clause = " AND ".join(
                    f"target.{self._quote_ident(f)} = source.{self._quote_ident(f)}"
                    for f in conflict_merge_fields
                )
                update_cols = [c for c in column_list if c not in conflict_merge_fields]
                insert_vals = ", ".join(
                    f"source.{self._quote_ident(c)}" for c in column_list
                )

                # BigQuery MERGE source: use multi-row UNION ALL of typed
                # SELECTs so each column has a stable name and resolved type.
                source_selects = []
                for row in batch:
                    select_parts = ", ".join(
                        f"{self._bq_literal(v, bq_type=types_map[c])} "
                        f"AS {self._quote_ident(c)}"
                        for v, c in zip(row, column_list, strict=False)
                    )
                    source_selects.append(f"SELECT {select_parts}")
                source_subquery = " UNION ALL ".join(source_selects)

                if update_cols:
                    update_set = ", ".join(
                        f"{self._quote_ident(c)} = source.{self._quote_ident(c)}"
                        for c in update_cols
                    )
                    # BigQuery has no ``IS DISTINCT FROM`` operator. Use
                    # a NULL-safe inequality via ``COALESCE`` to a
                    # type-compatible sentinel — but since sentinels are
                    # type-dependent, the simplest correct form is
                    # ``(target.c != source.c) OR (target.c IS NULL) !=
                    # (source.c IS NULL)``.
                    change_conditions = " OR ".join(
                        f"(target.{self._quote_ident(c)} != "
                        f"source.{self._quote_ident(c)}) "
                        f"OR ((target.{self._quote_ident(c)} IS NULL) != "
                        f"(source.{self._quote_ident(c)} IS NULL))"
                        for c in update_cols
                    )
                    matched_clause = (
                        f"WHEN MATCHED AND ({change_conditions}) "
                        f"THEN UPDATE SET {update_set} "
                    )
                else:
                    # All columns are conflict keys — there is nothing
                    # to update on match, so drop the WHEN MATCHED
                    # branch entirely (BigQuery rejects an empty
                    # ``UPDATE SET``).
                    matched_clause = ""

                sql = (
                    f"MERGE INTO {table_ref} AS target "
                    f"USING ({source_subquery}) AS source "
                    f"ON {on_clause} "
                    f"{matched_clause}"
                    f"WHEN NOT MATCHED THEN INSERT ({quoted_cols}) "
                    f"VALUES ({insert_vals})"
                )
            else:
                sql = f"INSERT INTO {table_ref} ({quoted_cols}) VALUES {value_rows}"

            result = self.execute_query(
                QueryWrapper(query=sql, name=table_path),
            )
            results.append(result)
            if result.failed():
                return results

        return results
