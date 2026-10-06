from __future__ import annotations

from typing import TYPE_CHECKING, Any

import duckdb
from nld.connector.base import (
    ConnectorDefinition,
    ConnectorDeployCapabilities,
    QueryExecResult,
    QueryExecResultStatus,
    QueryExecutionException,
    QueryOutputType,
    QueryWrapper,
    SQLDataConnector,
    SQLOperationType,
)
from nld.connector.duckdb.constants import DUCKDB_DIALECT
from nld.connector.duckdb.engine.duckdb_native.connection import (
    DuckDBConnectionWrapper,
)
from nld.connector.duckdb.engine.duckdb_native.query_wrapper import (
    DuckDBQueryWrapper,
)
from nld.connector.duckdb.engine.duckdb_native.utils import DuckDBUtil
from nld.logging.events import CSVFileWriteSuccessful
from nld.structure import Field, Structure
from nld.utils.datetime_util import get_current_datetime
from nld.utils.sqlglot import (
    identifier_list,
    literal_list,
    literal_value,
    quote_identifier,
    quote_table,
)
from nld.utils.sqlglot.base_ddl import BaseSqlglotDDLBuilder
from nld.utils.sqlglot.base_dml import BaseSqlglotDMLBuilder

if TYPE_CHECKING:
    from nld.connector.duckdb.engine.duckdb_native.adapter.pydantic import (
        NldBaseModelDuckDBManager,
    )
    from nld.connector.duckdb.service.data_profiler import (
        DuckDBDataProfiler,
    )
    from nld.connector.duckdb.service.structure_diff_ddl_statement_builder import (
        DuckDBStructureDiffDDLStatementBuilder,
    )
    from nld.connector.duckdb.service.structure_reader import (
        DuckDBStructureReader,
    )


class DuckDBSQLConnector(SQLDataConnector[DuckDBConnectionWrapper]):
    """Connector class for DuckDB connections.

    This class provides methods to execute queries, manage tables, and
    perform DML operations against a DuckDB database.
    """

    def __init__(self, connection_wrapper: DuckDBConnectionWrapper) -> None:
        super().__init__(connection_wrapper)

    @property
    def sqlglot_dialect(self) -> str:
        """The sqlglot dialect name for SQL rendering."""
        return DUCKDB_DIALECT

    def get_ddl_builder(self) -> BaseSqlglotDDLBuilder:
        """Return a DuckDB-specific DDL builder."""
        from nld.connector.duckdb.sqlglot import DuckDBSqlglotDDLBuilder

        return DuckDBSqlglotDDLBuilder()

    def get_structure_diff_ddl_statement_builder(
        self,
    ) -> DuckDBStructureDiffDDLStatementBuilder:
        """Return a DuckDB DDL generator for structure deployment."""
        from nld.connector.duckdb.service.structure_diff_ddl_statement_builder import (
            DuckDBStructureDiffDDLStatementBuilder,
        )

        return DuckDBStructureDiffDDLStatementBuilder()

    def get_connector_definition(self) -> ConnectorDefinition:
        """Return the static engine facts of the DuckDB connector."""
        from nld.connector.duckdb.connector_definition import (
            DUCKDB_CONNECTOR_DEFINITION,
        )

        return DUCKDB_CONNECTOR_DEFINITION

    def get_deploy_capabilities(self) -> ConnectorDeployCapabilities:
        """Return the declared DuckDB structure deployment capabilities."""
        from nld.connector.duckdb.service import (
            DUCKDB_DEPLOY_CAPABILITIES,
        )

        return DUCKDB_DEPLOY_CAPABILITIES

    def get_dml_builder(self) -> BaseSqlglotDMLBuilder:
        """Return a DuckDB-specific DML builder."""
        from nld.connector.duckdb.sqlglot import DuckDBSqlglotDMLBuilder

        return DuckDBSqlglotDMLBuilder()

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        if self.connection_wrapper.connection is None:
            raise ValueError(
                f"No connection available on "
                f"DuckDB connector {self.connection_wrapper.name}"
            )
        return self.connection_wrapper.connection

    def get_active_database(self) -> str | None:
        """Return the active catalog (database) for the connection."""
        return self.connection_wrapper.get_active_database()

    def get_model_manager(self) -> NldBaseModelDuckDBManager:
        """Return a DuckDB pydantic model manager."""
        from nld.connector.duckdb.engine.duckdb_native.adapter.pydantic import (
            NldBaseModelDuckDBManager,
        )

        return NldBaseModelDuckDBManager(connector=self)

    def get_structure_reader(self) -> DuckDBStructureReader:
        """Return a DuckDB structure reader for this connector."""
        from nld.connector.duckdb.service.structure_reader import (
            DuckDBStructureReader,
        )

        return DuckDBStructureReader(self)

    def get_data_profiler(self) -> DuckDBDataProfiler:
        """Return a DuckDB data profiler for this connector."""
        from nld.connector.duckdb.service.data_profiler import (
            DuckDBDataProfiler,
        )

        return DuckDBDataProfiler(self)

    def get_active_schema(self) -> str | None:
        """Return the active schema for the connection."""
        return self.connection_wrapper.get_active_schema()

    def log_execution_error(self, error: Exception) -> None:  # type: ignore[override]
        """Log execution errors."""
        self.log_error(f"DuckDB Error: {error}")

    def prepare_query_for_execution(
        self, query: str | QueryWrapper
    ) -> DuckDBQueryWrapper:
        if isinstance(query, DuckDBQueryWrapper):
            return query
        if isinstance(query, QueryWrapper):
            return DuckDBQueryWrapper(
                query=query.query,
                interpreted_query=query.interpreted_query,
                name=query.name,
                params=query.params,
                runtime_exception_message=query.runtime_exception_message,
            )
        if isinstance(query, str):
            return DuckDBQueryWrapper(query=query)
        raise NotImplementedError(
            f"Query type {type(query)} is not supported for DuckDB query."
        )

    def execute_query(self, query: str | QueryWrapper) -> QueryExecResult:
        """Execute a query against the DuckDB connection.

        Non-SELECT queries run inside an explicit transaction so that
        commit and rollback behave correctly (DuckDB defaults to
        auto-commit which makes bare commit/rollback no-ops).

        Args:
            query: The query wrapper or string to execute.

        Returns:
            The result of the query execution.
        """
        query_wrapper = self.prepare_query_for_execution(query)
        start_tst = get_current_datetime()
        query_wrapper.update_interpreted_query()
        self.log_debug(f"Query to be executed: {query_wrapper.interpreted_query}")
        expected_output = query_wrapper.get_expected_output_type()
        resolved_operation_type = query_wrapper.operation_type

        # Start an explicit transaction for non-SELECT so that
        # commit/rollback are effective (DuckDB auto-commits otherwise).
        if expected_output != QueryOutputType.DATASET:
            self.connection.begin()

        try:
            result_proxy = self.connection.execute(
                query_wrapper.get_interpreted_query()
            )

            message = None
            results = None
            row_count = None
            structure = None

            if expected_output == QueryOutputType.DATASET:
                description = result_proxy.description
                raw_rows = result_proxy.fetchall()
                if description:
                    col_names = [col[0] for col in description]
                    results = [
                        dict(zip(col_names, row, strict=False)) for row in raw_rows
                    ]
                else:
                    results = []
                structure = DuckDBUtil.get_structure_from_metadata(
                    result_metadata=result_proxy.description,
                    row_count=len(results),
                )
            elif expected_output == QueryOutputType.ROW_COUNT:
                # DuckDB returns affected row count in fetchone() for
                # INSERT/UPDATE/DELETE as a Count tuple, or via description.
                try:
                    count_row = result_proxy.fetchone()
                    if count_row is not None and isinstance(count_row, tuple):
                        row_count = count_row[0] if count_row else 0
                    else:
                        row_count = 0
                except duckdb.InvalidInputException:
                    # Some DDL-like DML statements don't return rows
                    row_count = 0
            else:
                message = (
                    f"{resolved_operation_type.value} statement executed successfully."
                    if resolved_operation_type is not None
                    else "Statement executed successfully."
                )

            if expected_output != QueryOutputType.DATASET:
                self.connection.commit()

            result = QueryExecResult(
                query_name=query_wrapper.name,
                exec_status=QueryExecResultStatus.SUCCESS,
                query=query_wrapper.get_interpreted_query(),
                query_id=None,
                output_structure=structure,
                start_tst=start_tst,
                end_tst=get_current_datetime(),
                message=message,
                operation_type=resolved_operation_type,
                row_count=row_count,
                result_data=results,
            )
            return result
        except BaseException as e:
            if expected_output != QueryOutputType.DATASET:
                self.connection.rollback()
            if isinstance(e, duckdb.Error):
                self.log_execution_error(e)
            raise

    def _build_copy_to_csv_statement(
        self,
        query_text: str,
        output_file_path: str,
        delimiter: str,
        include_header: bool,
    ) -> str:
        """Build a DuckDB ``COPY (...) TO file`` CSV statement."""
        inner_query = query_text.strip().rstrip(";")
        options = [
            "FORMAT CSV",
            f"DELIMITER {literal_value(delimiter, DUCKDB_DIALECT)}",
            f"HEADER {'true' if include_header else 'false'}",
        ]
        target = literal_value(output_file_path, DUCKDB_DIALECT)
        return f"COPY ({inner_query}) TO {target} ({', '.join(options)})"

    def export_query_to_csv(
        self,
        query: str | QueryWrapper,
        output_file_path: str,
        delimiter: str = ",",
        include_header: bool = True,
        encoding: str = "utf-8",
    ) -> int:
        """Export a SELECT result to CSV via DuckDB's native ``COPY ... TO``.

        DuckDB writes the file itself in UTF-8, so the result set never
        transits through Python before reaching the target CSV file.
        """
        self.assert_select_query(query)
        query_text = query.query if isinstance(query, QueryWrapper) else query
        copy_statement = self._build_copy_to_csv_statement(
            query_text=query_text,
            output_file_path=output_file_path,
            delimiter=delimiter,
            include_header=include_header,
        )
        try:
            result_proxy = self.connection.execute(copy_statement)
            count_row = result_proxy.fetchone()
        except duckdb.Error as error:
            self.log_execution_error(error)
            raise QueryExecutionException(error_message=str(error)) from error
        row_count = count_row[0] if count_row else 0
        self.log_event(
            CSVFileWriteSuccessful(
                object_type_name="QueryResult",
                file_path=output_file_path,
            ),
        )
        return row_count

    def execute_bulk_insert(
        self,
        schema_name: str,
        table_name: str,
        column_list: list[str],
        rows: list[tuple[Any, ...]],
        conflict_merge_fields: list[str] | None = None,
        page_size: int = 1000,
    ) -> None:
        """Execute a bulk INSERT by building complete statements with sqlglot."""
        self.execute_bulk_insert_with_result(
            schema_name=schema_name,
            table_name=table_name,
            column_list=column_list,
            rows=rows,
            conflict_merge_fields=conflict_merge_fields,
            batch_size=page_size,
        )

    def bulk_insert_into(
        self,
        table_path: str,
        rows: list[tuple[Any, ...]],
        column_list: list[str],
        conflict_merge_fields: list[str] | None = None,
        batch_size: int = 1000,
        technical_tracking_timestamp_columns: dict[str, str] | None = None,
        exclude_from_update: list[str] | None = None,
        expression_overrides: dict[str, str] | None = None,
        exclude_from_match: list[str] | None = None,
    ) -> list[QueryExecResult]:
        """Insert rows in batches and return one result per batch."""
        table_path = self.clean_object_path(table_path)
        schema_name, table_name = self._split_object_path(table_path)
        return self.execute_bulk_insert_with_result(
            schema_name=schema_name,
            table_name=table_name,
            column_list=column_list,
            rows=rows,
            conflict_merge_fields=conflict_merge_fields,
            batch_size=batch_size,
            technical_tracking_timestamp_columns=technical_tracking_timestamp_columns,
            exclude_from_update=exclude_from_update,
            expression_overrides=expression_overrides,
            exclude_from_match=exclude_from_match,
        )

    def execute_bulk_insert_with_result(
        self,
        schema_name: str,
        table_name: str,
        column_list: list[str],
        rows: list[tuple[Any, ...]],
        conflict_merge_fields: list[str] | None = None,
        batch_size: int = 1000,
        technical_tracking_timestamp_columns: dict[str, str] | None = None,
        exclude_from_update: list[str] | None = None,
        expression_overrides: dict[str, str] | None = None,
        exclude_from_match: list[str] | None = None,
    ) -> list[QueryExecResult]:
        """Execute a bulk INSERT and return one QueryExecResult per batch."""
        results: list[QueryExecResult] = []
        self.connection.begin()
        try:
            for batch_start in range(0, len(rows), batch_size):
                batch = rows[batch_start : batch_start + batch_size]
                query = self.get_dml_builder().build_bulk_insert_query(
                    schema_name=schema_name,
                    table_name=table_name,
                    insert_column_list=column_list,
                    rows=batch,
                    conflict_merge_fields=conflict_merge_fields,
                    technical_tracking_timestamp_columns=technical_tracking_timestamp_columns,
                    exclude_from_update=exclude_from_update,
                    expression_overrides=expression_overrides,
                    exclude_from_match=exclude_from_match,
                )
                start_tst = get_current_datetime()
                self.connection.execute(query)
                results.append(
                    QueryExecResult(
                        query_name=f"{schema_name}.{table_name}",
                        exec_status=QueryExecResultStatus.SUCCESS,
                        query=query,
                        query_id=None,
                        output_structure=None,
                        start_tst=start_tst,
                        end_tst=get_current_datetime(),
                        operation_type=SQLOperationType.INSERT,
                        row_count=len(batch),
                    ),
                )
            self.connection.commit()
        except BaseException:
            # Must rollback on ANY exception (not just duckdb.Error)
            # because the SQL builder can raise ValueError before
            # executing any SQL, leaving the connection in an open
            # transaction that would poison subsequent writes.
            self.connection.rollback()
            raise
        return results

    # DDL operations

    @staticmethod
    def clean_object_path(object_path: str) -> str:
        """Cleans the object path by checking specification compliance."""
        return object_path

    def truncate_table(self, table_path: str, **kwargs: Any) -> QueryExecResult:
        table_path = self.clean_object_path(table_path)
        schema_name, table_name = self._split_object_path(table_path)
        return self.execute_query(
            query=QueryWrapper(
                query=self.get_ddl_builder().build_truncate_table(
                    schema=schema_name,
                    table=table_name,
                ),
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
        schema_name, table_name = self._split_object_path(table_path)
        return self.execute_query(
            query=QueryWrapper(
                query=self.get_ddl_builder().build_drop_table(
                    schema=schema_name,
                    table=table_name,
                    if_exists=if_exists,
                ),
                name=table_path,
            ),
        )

    _UNBOUNDED_STRING_TYPES = frozenset({"VARCHAR", "TEXT", "CHARACTER VARYING"})

    @staticmethod
    def _build_column_type(field: Field) -> str:
        """Build a DuckDB-safe column type expression from a Field.

        Normalizes TEXT and CHARACTER VARYING to VARCHAR (DuckDB
        info_schema always returns VARCHAR).  Strips length from
        unbounded string types.  Preserves DECIMAL(length, precision).
        """
        data_type = field.data_type.upper()
        if data_type in DuckDBSQLConnector._UNBOUNDED_STRING_TYPES:
            return "VARCHAR"
        if field.length > 0 and field.precision > 0:
            return f"{data_type}({field.length}, {field.precision})"
        if field.length > 0:
            return f"{data_type}({field.length})"
        return data_type

    def create_table(
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
                self.drop_table(table_path, if_exists=True)
                self.log_info(f"Table {table_path} dropped.")
            elif table_exists == "fail":
                raise ValueError(f"Table {table_path} already exists")

        table_path = self.clean_object_path(table_path)
        schema_name, table_name = self._split_object_path(table_path)

        columns = [
            (field.name, self._build_column_type(field), field.is_mandatory())
            for field in structure.fields.values()
        ]

        if override_primary_key_fields:
            primary_key_fields = override_primary_key_fields
        elif structure.has_primary_key():
            primary_key_fields = [
                field.name for field in structure.get_primary_key_fields()
            ]
        else:
            primary_key_fields = None

        create_sql = self.get_ddl_builder().build_create_table(
            schema=schema_name,
            table=table_name,
            columns=columns,
            primary_key_fields=primary_key_fields,
        )
        return self.execute_query(query=create_sql)

    def does_object_exist(self, object_path: str, **kwargs: Any) -> bool:
        object_path = self.clean_object_path(object_path)
        schema_name, table_name = self._split_object_path(object_path)
        query_exec_result = self.execute_query(
            self.get_ddl_builder().build_exists_query(
                schema=schema_name,
                table=table_name,
            )
        )
        result: bool = query_exec_result.get_result_single_value()
        return result

    def get_column_names(self, object_path: str, **kwargs: Any) -> list[str]:
        object_path = self.clean_object_path(object_path)
        schema_name, table_name = self._split_object_path(object_path)
        query_exec_result = self.execute_query(
            self.get_ddl_builder().build_column_names_query(
                schema=schema_name,
                table=table_name,
            )
        )
        return [
            record["column_name"] for record in query_exec_result.get_result_records()
        ]

    def create_index(
        self,
        index_name: str,
        table_path: str,
        columns: list[str],
        unique: bool = False,
        use_constraint: bool = False,
    ) -> QueryExecResult:
        """Create an index on a table.

        DuckDB does not support ALTER TABLE ADD CONSTRAINT UNIQUE,
        so both use_constraint=True and use_constraint=False use
        CREATE [UNIQUE] INDEX.
        """
        table_path = self.clean_object_path(table_path)
        schema_name, table_name = self._split_object_path(table_path)

        ddl_builder = self.get_ddl_builder()
        create_sql = ddl_builder.build_create_index(
            index_name=index_name,
            schema=schema_name,
            table=table_name,
            columns=columns,
            unique=unique,
            if_not_exists=True,
        )

        return self.execute_query(query=create_sql)

    # DML operations

    def insert_into(
        self,
        table_path: str,
        data: dict[str, Any],
        **kwargs: Any,
    ) -> QueryExecResult:
        """Insert a single row into a DuckDB table."""
        table_path = self.clean_object_path(table_path)
        schema_name, table_name = self._split_object_path(table_path)
        columns = list(data.keys())
        values = list(data.values())

        table_ref = quote_table(
            schema=schema_name, table=table_name, dialect=DUCKDB_DIALECT
        )
        cols = identifier_list(columns, dialect=DUCKDB_DIALECT)
        vals = literal_list(values, dialect=DUCKDB_DIALECT)

        insert_query = f"INSERT INTO {table_ref} ({cols}) VALUES ({vals})"
        return self.execute_query(insert_query)

    def upsert_into(
        self,
        table_path: str,
        data: dict[str, Any],
        upsert_fields: list[str],
        **kwargs: Any,
    ) -> QueryExecResult:
        """Insert a row or update it on conflict in DuckDB.

        Uses INSERT ... ON CONFLICT DO UPDATE SET.
        """
        table_path = self.clean_object_path(table_path)
        schema_name, table_name = self._split_object_path(table_path)
        columns = list(data.keys())
        values = list(data.values())
        update_fields = [col for col in columns if col not in upsert_fields]

        if not update_fields:
            raise ValueError("No fields to update after excluding upsert_fields")

        table_ref = quote_table(
            schema=schema_name, table=table_name, dialect=DUCKDB_DIALECT
        )
        cols = identifier_list(columns, dialect=DUCKDB_DIALECT)
        vals = literal_list(values, dialect=DUCKDB_DIALECT)
        conflict_cols = identifier_list(upsert_fields, dialect=DUCKDB_DIALECT)
        update_set = ", ".join(
            f"{quote_identifier(col, dialect=DUCKDB_DIALECT)} = "
            f"EXCLUDED.{quote_identifier(col, dialect=DUCKDB_DIALECT)}"
            for col in update_fields
        )

        upsert_query = (
            f"INSERT INTO {table_ref} ({cols}) VALUES ({vals}) "
            f"ON CONFLICT ({conflict_cols}) DO UPDATE SET {update_set}"
        )
        return self.execute_query(upsert_query)

    def delete_from(
        self,
        table_path: str,
        where_conditions: dict[str, Any],
        **kwargs: Any,
    ) -> QueryExecResult:
        """Delete rows from a DuckDB table matching the conditions."""
        if not where_conditions:
            raise ValueError(
                "where_conditions must not be empty to prevent accidental full deletes"
            )
        table_path = self.clean_object_path(table_path)
        schema_name, table_name = self._split_object_path(table_path)

        dml_builder = self.get_dml_builder()
        conditions = [
            dml_builder.equality_clause(field=field, value=value)
            for field, value in where_conditions.items()
        ]
        where = dml_builder.and_clause(conditions)

        table_ref = quote_table(
            schema=schema_name, table=table_name, dialect=DUCKDB_DIALECT
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
        """Insert rows into a DuckDB table from a SELECT query."""
        table_path = self.clean_object_path(table_path)
        schema_name, table_name = self._split_object_path(table_path)
        insert_query = self.get_dml_builder().build_insert_from_select_query(
            schema_name=schema_name,
            table_name=table_name,
            selection_query=sql_query,
            insert_column_list=column_list,
        )
        return self.execute_query(
            query=QueryWrapper(query=insert_query, name=table_path),
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
        """Insert rows from a SELECT query, updating on conflict."""
        table_path = self.clean_object_path(table_path)
        schema_name, table_name = self._split_object_path(table_path)
        upsert_query = self.get_dml_builder().build_insert_from_select_query(
            schema_name=schema_name,
            table_name=table_name,
            selection_query=sql_query,
            insert_column_list=column_list,
            conflict_merge_fields=upsert_fields,
            exclude_from_update=exclude_from_update,
            expression_overrides=expression_overrides,
            exclude_from_match=exclude_from_match,
        )
        return self.execute_query(
            query=QueryWrapper(query=upsert_query, name=table_path),
        )

    def delete_from_query(
        self,
        table_path: str,
        sql_query: str,
        key_columns: list[str],
        **kwargs: Any,
    ) -> QueryExecResult:
        """Delete rows from a DuckDB table matching keys from a query."""
        table_path = self.clean_object_path(table_path)
        schema_name, table_name = self._split_object_path(table_path)

        table_ref = quote_table(
            schema=schema_name, table=table_name, dialect=DUCKDB_DIALECT
        )
        key_cols = identifier_list(key_columns, dialect=DUCKDB_DIALECT)

        delete_query = (
            f"DELETE FROM {table_ref} "
            f"WHERE ({key_cols}) IN (SELECT {key_cols} FROM ({sql_query}) AS _subq)"
        )
        return self.execute_query(
            query=QueryWrapper(query=delete_query, name=table_path),
        )

    def _split_object_path(self, object_path: str) -> tuple[str, str]:
        """Split a qualified object path into schema and object name."""
        if "." in object_path:
            schema_name, table_name = object_path.split(".", maxsplit=1)
            return schema_name, table_name
        return self.get_active_schema() or "main", object_path
