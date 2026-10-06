from __future__ import annotations

import csv
import sqlite3
from typing import TYPE_CHECKING, Any

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
from nld.connector.sqlite.constants import SQLITE_DIALECT, SQLITE_SCHEMA
from nld.connector.sqlite.engine.sqlite_native.connection import (
    SQLiteConnectionWrapper,
)
from nld.connector.sqlite.engine.sqlite_native.query_wrapper import (
    SQLiteQueryWrapper,
)
from nld.connector.sqlite.engine.sqlite_native.utils import SQLiteUtil
from nld.logging.events import CSVFileWriteSuccessful
from nld.structure import Field, Structure
from nld.utils.datetime_util import get_current_datetime
from nld.utils.sqlglot import (
    identifier_list,
    literal_list,
    quote_identifier,
)
from nld.utils.sqlglot.base_ddl import BaseSqlglotDDLBuilder
from nld.utils.sqlglot.base_dml import BaseSqlglotDMLBuilder

if TYPE_CHECKING:
    from nld.connector.sqlite.engine.sqlite_native.adapter.pydantic import (
        NldBaseModelSQLiteManager,
    )
    from nld.connector.sqlite.service.data_profiler import (
        SQLiteDataProfiler,
    )
    from nld.connector.sqlite.service.structure_diff_ddl_statement_builder import (
        SQLiteStructureDiffDDLStatementBuilder,
    )
    from nld.connector.sqlite.service.structure_reader import (
        SQLiteStructureReader,
    )


class SQLiteSQLConnector(SQLDataConnector[SQLiteConnectionWrapper]):
    """Connector class for SQLite connections.

    Executes queries, manages tables and performs DML against a SQLite
    database file through the standard library ``sqlite3`` driver.

    SQLite has one namespace, so every ``schema.table`` path resolves to
    ``table`` in the always-attached ``main`` database: a structure written
    for a PostgreSQL schema deploys unchanged on a local file.
    """

    def __init__(self, connection_wrapper: SQLiteConnectionWrapper) -> None:
        super().__init__(connection_wrapper)

    @property
    def sqlglot_dialect(self) -> str:
        """The sqlglot dialect name for SQL rendering."""
        return SQLITE_DIALECT

    def get_ddl_builder(self) -> BaseSqlglotDDLBuilder:
        """Return a SQLite-specific DDL builder."""
        from nld.connector.sqlite.sqlglot import SQLiteSqlglotDDLBuilder

        return SQLiteSqlglotDDLBuilder()

    def get_dml_builder(self) -> BaseSqlglotDMLBuilder:
        """Return a SQLite-specific DML builder."""
        from nld.connector.sqlite.sqlglot import SQLiteSqlglotDMLBuilder

        return SQLiteSqlglotDMLBuilder()

    def get_structure_diff_ddl_statement_builder(
        self,
    ) -> SQLiteStructureDiffDDLStatementBuilder:
        """Return a SQLite DDL generator for structure deployment."""
        from nld.connector.sqlite.service.structure_diff_ddl_statement_builder import (
            SQLiteStructureDiffDDLStatementBuilder,
        )

        return SQLiteStructureDiffDDLStatementBuilder()

    def get_connector_definition(self) -> ConnectorDefinition:
        """Return the static engine facts of the SQLite connector."""
        from nld.connector.sqlite.connector_definition import (
            SQLITE_CONNECTOR_DEFINITION,
        )

        return SQLITE_CONNECTOR_DEFINITION

    def get_deploy_capabilities(self) -> ConnectorDeployCapabilities:
        """Return the declared SQLite structure deployment capabilities."""
        from nld.connector.sqlite.service import SQLITE_DEPLOY_CAPABILITIES

        return SQLITE_DEPLOY_CAPABILITIES

    def get_model_manager(self) -> NldBaseModelSQLiteManager:
        """Return a SQLite pydantic model manager."""
        from nld.connector.sqlite.engine.sqlite_native.adapter.pydantic import (
            NldBaseModelSQLiteManager,
        )

        return NldBaseModelSQLiteManager(connector=self)

    def get_structure_reader(self) -> SQLiteStructureReader:
        """Return a SQLite structure reader for this connector."""
        from nld.connector.sqlite.service.structure_reader import (
            SQLiteStructureReader,
        )

        return SQLiteStructureReader(self)

    def get_data_profiler(self) -> SQLiteDataProfiler:
        """Return a SQLite data profiler for this connector."""
        from nld.connector.sqlite.service.data_profiler import (
            SQLiteDataProfiler,
        )

        return SQLiteDataProfiler(self)

    @property
    def connection(self) -> sqlite3.Connection:
        if self.connection_wrapper.connection is None:
            raise ValueError(
                f"No connection available on "
                f"SQLite connector {self.connection_wrapper.name}"
            )
        return self.connection_wrapper.connection

    def get_active_database(self) -> str | None:
        """Return the database file backing the connection."""
        return self.connection_wrapper.get_active_database()

    def get_active_schema(self) -> str | None:
        """Return the active schema, always ``main`` on SQLite."""
        return SQLITE_SCHEMA

    def does_schema_exist(self, schema: str, **kwargs: Any) -> bool:
        """Return whether the schema exists, which on SQLite is always true."""
        return True

    def log_execution_error(self, error: Exception) -> None:  # type: ignore[override]
        """Log execution errors."""
        self.log_error(f"SQLite Error: {error}")

    def prepare_query_for_execution(
        self, query: str | QueryWrapper
    ) -> SQLiteQueryWrapper:
        if isinstance(query, SQLiteQueryWrapper):
            return query
        if isinstance(query, QueryWrapper):
            return SQLiteQueryWrapper(
                query=query.query,
                interpreted_query=query.interpreted_query,
                name=query.name,
                params=query.params,
                runtime_exception_message=query.runtime_exception_message,
            )
        if isinstance(query, str):
            return SQLiteQueryWrapper(query=query)
        raise NotImplementedError(
            f"Query type {type(query)} is not supported for SQLite query."
        )

    def execute_query(self, query: str | QueryWrapper) -> QueryExecResult:
        """Execute a query against the SQLite connection.

        The connection is opened in autocommit mode, so non-SELECT queries
        run inside an explicit transaction started here: SQLite would
        otherwise leave DDL outside any transaction and make a rollback a
        no-op.

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

        in_transaction = expected_output != QueryOutputType.DATASET
        if in_transaction:
            self.connection.execute("BEGIN")

        try:
            cursor = self.connection.execute(query_wrapper.get_interpreted_query())

            message = None
            results = None
            row_count = None
            structure = None

            if expected_output == QueryOutputType.DATASET:
                description = cursor.description
                raw_rows = cursor.fetchall()
                if description:
                    column_names = [column[0] for column in description]
                    results = [
                        dict(zip(column_names, row, strict=False)) for row in raw_rows
                    ]
                else:
                    results = []
                structure = SQLiteUtil.get_structure_from_metadata(
                    result_metadata=description,
                    row_count=len(results),
                    first_row=raw_rows[0] if raw_rows else None,
                )
            elif expected_output == QueryOutputType.ROW_COUNT:
                row_count = cursor.rowcount if cursor.rowcount >= 0 else 0
            else:
                message = (
                    f"{resolved_operation_type.value} statement executed successfully."
                    if resolved_operation_type is not None
                    else "Statement executed successfully."
                )

            if in_transaction:
                self.connection.execute("COMMIT")

            return QueryExecResult(
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
        except BaseException as error:
            if in_transaction:
                self.connection.execute("ROLLBACK")
            if isinstance(error, sqlite3.Error):
                self.log_execution_error(error)
            raise

    def export_query_to_csv(
        self,
        query: str | QueryWrapper,
        output_file_path: str,
        delimiter: str = ",",
        include_header: bool = True,
        encoding: str = "utf-8",
    ) -> int:
        """Export a SELECT result to CSV.

        SQLite has no server-side COPY (the ``.mode csv`` output is a shell
        feature, not an engine one), so the rows are written from Python.
        """
        self.assert_select_query(query)
        query_text = query.query if isinstance(query, QueryWrapper) else query
        try:
            cursor = self.connection.execute(query_text)
            column_names = [column[0] for column in cursor.description or []]
            rows = cursor.fetchall()
        except sqlite3.Error as error:
            self.log_execution_error(error)
            raise QueryExecutionException(error_message=str(error)) from error

        with open(output_file_path, "w", encoding=encoding, newline="") as output_file:
            writer = csv.writer(output_file, delimiter=delimiter)
            if include_header:
                writer.writerow(column_names)
            writer.writerows(rows)

        self.log_event(
            CSVFileWriteSuccessful(
                object_type_name="QueryResult",
                file_path=output_file_path,
            ),
        )
        return len(rows)

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
        self.connection.execute("BEGIN")
        try:
            for batch_start in range(0, len(rows), batch_size):
                batch = rows[batch_start : batch_start + batch_size]
                query = self.get_dml_builder().build_bulk_insert_query(
                    schema_name=SQLITE_SCHEMA,
                    table_name=table_name,
                    insert_column_list=column_list,
                    rows=batch,
                    conflict_merge_fields=conflict_merge_fields,
                    technical_tracking_timestamp_columns=(
                        technical_tracking_timestamp_columns
                    ),
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
            self.connection.execute("COMMIT")
        except BaseException:
            # Any exception must roll back, not only sqlite3.Error: the SQL
            # builder can raise before a single statement runs, which would
            # otherwise leave the transaction open and poison later writes.
            self.connection.execute("ROLLBACK")
            raise
        return results

    # DDL operations

    @staticmethod
    def clean_object_path(object_path: str) -> str:
        """Resolve a qualified object path to its bare object name.

        SQLite has one namespace, so a declared schema carries no meaning
        beyond the name of the attached database.
        """
        if "." in object_path:
            return object_path.split(".", maxsplit=1)[1]
        return object_path

    def _split_object_path(self, object_path: str) -> tuple[str, str]:
        """Split a qualified object path into the SQLite namespace and name."""
        return SQLITE_SCHEMA, self.clean_object_path(object_path)

    def truncate_table(self, table_path: str, **kwargs: Any) -> QueryExecResult:
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

    @staticmethod
    def _build_column_type(field: Field) -> str:
        """Build a SQLite column type expression from a Field.

        The declared type is emitted verbatim, length and precision
        included: SQLite stores the string as written and hands it back
        unchanged, so the read-back type matches the declaration exactly.
        """
        data_type = field.data_type.upper()
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

        if self.does_object_exist(table_path):
            if table_exists == "skip":
                return None
            if table_exists == "replace":
                self.drop_table(table_path, if_exists=True)
                self.log_info(f"Table {table_path} dropped.")
            elif table_exists == "fail":
                raise ValueError(f"Table {table_path} already exists")

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

    def create_or_replace_view(
        self,
        view_path: str,
        sql_query: str,
    ) -> QueryExecResult:
        """Create or replace a view.

        SQLite has no CREATE OR REPLACE VIEW, so the view is dropped first.
        """
        schema_name, view_name = self._split_object_path(view_path)
        ddl_builder = self.get_ddl_builder()
        self.execute_query(
            query=QueryWrapper(
                query=ddl_builder.build_drop_view(
                    schema=schema_name,
                    table=view_name,
                    if_exists=True,
                ),
                name=view_path,
            ),
        )
        table_ref = quote_identifier(view_name, dialect=SQLITE_DIALECT)
        return self.execute_query(
            query=QueryWrapper(
                query=f"CREATE VIEW {table_ref} AS {sql_query}",
                name=view_path,
            ),
        )

    def create_table_as(
        self,
        table_path: str,
        sql_query: str,
    ) -> QueryExecResult:
        """Create a table from a SELECT query, on the bare object name."""
        return super().create_table_as(
            table_path=self.clean_object_path(table_path),
            sql_query=sql_query,
        )

    def does_object_exist(self, object_path: str, **kwargs: Any) -> bool:
        schema_name, table_name = self._split_object_path(object_path)
        query_exec_result = self.execute_query(
            self.get_ddl_builder().build_exists_query(
                schema=schema_name,
                table=table_name,
            )
        )
        return bool(query_exec_result.get_result_single_value())

    def get_column_names(self, object_path: str, **kwargs: Any) -> list[str]:
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

        SQLite has no ALTER TABLE ADD CONSTRAINT, so a unique constraint is
        a unique index whatever ``use_constraint`` asks for.
        """
        schema_name, table_name = self._split_object_path(table_path)
        return self.execute_query(
            query=self.get_ddl_builder().build_create_index(
                index_name=index_name,
                schema=schema_name,
                table=table_name,
                columns=columns,
                unique=unique,
                if_not_exists=True,
            ),
        )

    # DML operations

    def _table_reference(self, table_path: str) -> str:
        """Render the quoted table reference for a declared object path."""
        return quote_identifier(
            self.clean_object_path(table_path),
            dialect=SQLITE_DIALECT,
        )

    def insert_into(
        self,
        table_path: str,
        data: dict[str, Any],
        **kwargs: Any,
    ) -> QueryExecResult:
        """Insert a single row into a SQLite table."""
        columns = list(data.keys())
        values = list(data.values())
        cols = identifier_list(columns, dialect=SQLITE_DIALECT)
        vals = literal_list(values, dialect=SQLITE_DIALECT)
        return self.execute_query(
            f"INSERT INTO {self._table_reference(table_path)} ({cols}) VALUES ({vals})"
        )

    def upsert_into(
        self,
        table_path: str,
        data: dict[str, Any],
        upsert_fields: list[str],
        **kwargs: Any,
    ) -> QueryExecResult:
        """Insert a row or update it on conflict in SQLite."""
        columns = list(data.keys())
        values = list(data.values())
        update_fields = [column for column in columns if column not in upsert_fields]

        if not update_fields:
            raise ValueError("No fields to update after excluding upsert_fields")

        cols = identifier_list(columns, dialect=SQLITE_DIALECT)
        vals = literal_list(values, dialect=SQLITE_DIALECT)
        conflict_cols = identifier_list(upsert_fields, dialect=SQLITE_DIALECT)
        update_set = ", ".join(
            f"{quote_identifier(column, dialect=SQLITE_DIALECT)} = "
            f"EXCLUDED.{quote_identifier(column, dialect=SQLITE_DIALECT)}"
            for column in update_fields
        )
        return self.execute_query(
            f"INSERT INTO {self._table_reference(table_path)} ({cols}) "
            f"VALUES ({vals}) "
            f"ON CONFLICT ({conflict_cols}) DO UPDATE SET {update_set}"
        )

    def delete_from(
        self,
        table_path: str,
        where_conditions: dict[str, Any],
        **kwargs: Any,
    ) -> QueryExecResult:
        """Delete rows from a SQLite table matching the conditions."""
        if not where_conditions:
            raise ValueError(
                "where_conditions must not be empty to prevent accidental full deletes"
            )
        dml_builder = self.get_dml_builder()
        conditions = [
            dml_builder.equality_clause(field=field, value=value)
            for field, value in where_conditions.items()
        ]
        where = dml_builder.and_clause(conditions)
        return self.execute_query(
            f"DELETE FROM {self._table_reference(table_path)} WHERE {where}"
        )

    def insert_into_from_query(
        self,
        table_path: str,
        sql_query: str,
        column_list: list[str],
        **kwargs: Any,
    ) -> QueryExecResult:
        """Insert rows into a SQLite table from a SELECT query."""
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
        """Delete rows from a SQLite table matching keys from a query."""
        key_cols = identifier_list(key_columns, dialect=SQLITE_DIALECT)
        delete_query = (
            f"DELETE FROM {self._table_reference(table_path)} "
            f"WHERE ({key_cols}) IN (SELECT {key_cols} FROM ({sql_query}) AS _subq)"
        )
        return self.execute_query(
            query=QueryWrapper(query=delete_query, name=table_path),
        )

    def get_row_count(
        self,
        object_path: str,
        where_conditions: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> int:
        """Count rows, resolving the declared path to its bare object name."""
        return super().get_row_count(
            object_path=self.clean_object_path(object_path),
            where_conditions=where_conditions,
            **kwargs,
        )
