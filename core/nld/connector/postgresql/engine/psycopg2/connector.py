from __future__ import annotations

from typing import TYPE_CHECKING, Any

import psycopg2
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
from nld.connector.postgresql.engine.psycopg2.connection import (
    Psycopg2SQLConnectionWrapper,
)
from nld.connector.postgresql.engine.psycopg2.query_wrapper import (
    Psycopg2QueryWrapper,
)
from nld.connector.postgresql.engine.psycopg2.utils import Psycopg2SQLUtil
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
from nld.utils.sqlglot.utils import POSTGRES_DIALECT
from psycopg2.extensions import connection as Psycopg2Connection
from psycopg2.extras import RealDictCursor

if TYPE_CHECKING:
    from nld.connector.postgresql.engine.psycopg2.adapter.pydantic import (
        NldBaseModelPostgreSQLManager,
    )
    from nld.connector.postgresql.service.data_profiler import (
        PostgreSQLDataProfiler,
    )
    from nld.connector.postgresql.service.structure_diff_ddl_statement_builder import (
        PostgreSQLStructureDiffDDLStatementBuilder,
    )
    from nld.connector.postgresql.service.structure_reader import (
        PostgreSQLStructureReader,
    )


class Psycopg2SQLConnector(SQLDataConnector[Psycopg2SQLConnectionWrapper]):
    """Connector class for PostgreSQL connections.

    This class provides methods to execute queries, set schemas, and
    truncate tables. It extends the base DataConnector class and implements
    PostgreSQL-specific functionality.
    """

    def __init__(self, connection_wrapper: Psycopg2SQLConnectionWrapper) -> None:
        """Initialize the PostgreSQL service with a connection wrapper.

        Args:
            connection_wrapper: The connection wrapper for PostgreSQL.
        """
        super().__init__(connection_wrapper)

    @property
    def sqlglot_dialect(self) -> str:
        """The sqlglot dialect name for SQL rendering."""
        return "postgres"

    def get_ddl_builder(self) -> BaseSqlglotDDLBuilder:
        """Return a PostgreSQL-specific DDL builder."""
        from nld.connector.postgresql.sqlglot import PostgreSQLSqlglotDDLBuilder

        return PostgreSQLSqlglotDDLBuilder()

    def get_structure_diff_ddl_statement_builder(
        self,
    ) -> PostgreSQLStructureDiffDDLStatementBuilder:
        """Return a PostgreSQL DDL generator for structure deployment."""
        from nld.connector.postgresql.service import (
            PostgreSQLStructureDiffDDLStatementBuilder,
        )

        return PostgreSQLStructureDiffDDLStatementBuilder()

    def get_connector_definition(self) -> ConnectorDefinition:
        """Return the static engine facts of the PostgreSQL connector."""
        from nld.connector.postgresql.connector_definition import (
            POSTGRESQL_CONNECTOR_DEFINITION,
        )

        return POSTGRESQL_CONNECTOR_DEFINITION

    def get_deploy_capabilities(self) -> ConnectorDeployCapabilities:
        """Return the declared PostgreSQL structure deployment capabilities."""
        from nld.connector.postgresql.service import (
            POSTGRESQL_DEPLOY_CAPABILITIES,
        )

        return POSTGRESQL_DEPLOY_CAPABILITIES

    def get_dml_builder(self) -> BaseSqlglotDMLBuilder:
        """Return a PostgreSQL-specific DML builder."""
        from nld.connector.postgresql.sqlglot import PostgreSQLSqlglotDMLBuilder

        return PostgreSQLSqlglotDMLBuilder()

    @property
    def connection(self) -> Psycopg2Connection:
        if self.connection_wrapper.connection is None:
            raise ValueError(
                f"No connection available on "
                f"PSQL connector {self.connection_wrapper.name}"
            )
        return self.connection_wrapper.connection

    def get_active_database(self) -> str | None:
        """Return the active catalog (database) for the connection."""
        return self.connection_wrapper.get_active_database()

    def get_model_manager(self) -> NldBaseModelPostgreSQLManager:
        """Return a PostgreSQL pydantic model manager."""
        from nld.connector.postgresql.engine.psycopg2.adapter.pydantic import (
            NldBaseModelPostgreSQLManager,
        )

        return NldBaseModelPostgreSQLManager(connector=self)

    def get_structure_reader(self) -> PostgreSQLStructureReader:
        """Return a PostgreSQL structure reader for this connector."""
        from nld.connector.postgresql.service.structure_reader import (
            PostgreSQLStructureReader,
        )

        return PostgreSQLStructureReader(self)

    def get_data_profiler(self) -> PostgreSQLDataProfiler:
        """Return a PostgreSQL data profiler for this connector."""
        from nld.connector.postgresql.service.data_profiler import (
            PostgreSQLDataProfiler,
        )

        return PostgreSQLDataProfiler(self)

    def get_active_schema(self) -> str | None:
        """Return the active schema for the connection."""
        return self.connection_wrapper.get_active_schema()

    def log_execution_error(self, error: psycopg2.Error) -> None:  # type: ignore[override]
        """Log execution errors.

        Args:
            error: The error to log.
        """
        self.log_error(Psycopg2SQLUtil.get_standard_error_message(error))

    def get_active_cursor(self) -> RealDictCursor:
        assert self.connection is not None
        return self.connection.cursor(cursor_factory=RealDictCursor)

    def prepare_query_for_execution(
        self, query: str | QueryWrapper
    ) -> Psycopg2QueryWrapper:
        if isinstance(query, Psycopg2QueryWrapper):
            return query
        if isinstance(query, QueryWrapper):
            return Psycopg2QueryWrapper(
                query=query.query,
                interpreted_query=query.interpreted_query,
                name=query.name,
                params=query.params,
                runtime_exception_message=query.runtime_exception_message,
            )
        if isinstance(query, str):
            return Psycopg2QueryWrapper(query=query)
        raise NotImplementedError(
            f"Query type {type(query)} is not supported for PostgreSQL query."
        )

    def execute_query(self, query: str | QueryWrapper) -> QueryExecResult:
        """Execute a query using the provided query wrapper.

        Args:
            query: The query wrapper containing the query and parameters or
                the query only.

        Returns:
            The result of the query execution.
        """
        query_wrapper = self.prepare_query_for_execution(query)
        cur = self.get_active_cursor()
        start_tst = get_current_datetime()
        query_wrapper.update_interpreted_query()
        self.log_debug(f"Query to be executed: {query_wrapper.interpreted_query}")
        expected_output = query_wrapper.get_expected_output_type()
        resolved_operation_type = query_wrapper.operation_type
        try:
            cur.execute(query_wrapper.get_interpreted_query())

            message = None
            results = None
            row_count = None
            structure = None

            if expected_output == QueryOutputType.DATASET:
                results = cur.fetchall() if cur.description else []
                structure = Psycopg2SQLUtil.get_structure_from_metadata(
                    result_metadata=cur.description,
                    row_count=len(results),
                )
            elif expected_output == QueryOutputType.ROW_COUNT:
                row_count = (
                    cur.rowcount
                    if cur.rowcount is not None and cur.rowcount >= 0
                    else 0
                )
            else:
                message = (
                    f"{resolved_operation_type.value} statement executed successfully."
                    if resolved_operation_type is not None
                    else "Statement executed successfully."
                )

            # A statement returning no result set is never a read, whatever
            # its classification: commit it so unclassified DDL cannot keep
            # its locks until the connection's next commit.
            if expected_output != QueryOutputType.DATASET or cur.description is None:
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
        except psycopg2.Error as e:
            self.connection.rollback()
            self.log_execution_error(e)
            raise e
        finally:
            cur.close()

    def _build_copy_to_csv_statement(
        self,
        query_text: str,
        delimiter: str,
        include_header: bool,
    ) -> str:
        """Build a PostgreSQL ``COPY (...) TO STDOUT`` CSV statement."""
        inner_query = query_text.strip().rstrip(";")
        options = [
            "FORMAT CSV",
            f"DELIMITER {literal_value(delimiter, POSTGRES_DIALECT)}",
        ]
        if include_header:
            options.append("HEADER true")
        return f"COPY ({inner_query}) TO STDOUT WITH ({', '.join(options)})"

    def export_query_to_csv(
        self,
        query: str | QueryWrapper,
        output_file_path: str,
        delimiter: str = ",",
        include_header: bool = True,
        encoding: str = "utf-8",
    ) -> int:
        """Export a SELECT result to CSV via psycopg2 ``copy_expert``.

        Streaming the result through PostgreSQL's native ``COPY`` avoids
        materializing the whole dataset in memory before writing it.
        """
        self.assert_select_query(query)
        query_text = query.query if isinstance(query, QueryWrapper) else query
        copy_statement = self._build_copy_to_csv_statement(
            query_text=query_text,
            delimiter=delimiter,
            include_header=include_header,
        )
        cursor = self.get_active_cursor()
        try:
            with open(
                output_file_path,
                mode="w",
                encoding=encoding,
                newline="",
            ) as csv_file:
                cursor.copy_expert(
                    sql=copy_statement,
                    file=csv_file,
                )
            row_count = cursor.rowcount
            self.connection.commit()
        except psycopg2.Error as error:
            self.connection.rollback()
            self.log_execution_error(error)
            raise QueryExecutionException(
                error_message=Psycopg2SQLUtil.get_standard_error_message(error),
            ) from error
        finally:
            cursor.close()
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
        """Execute a bulk INSERT by building complete statements with sqlglot.

        Rows are split into batches of `page_size` and each batch
        is executed as a separate INSERT statement with inlined
        literal values.

        Args:
            schema_name: target schema name.
            table_name: target table name.
            column_list: columns to insert into.
            rows: list of row tuples to insert.
            conflict_merge_fields: optional list of conflict
                target columns for ON CONFLICT.
            page_size: number of rows per batch (default 1000).
        """
        cursor = self.get_active_cursor()
        try:
            for batch_start in range(0, len(rows), page_size):
                batch = rows[batch_start : batch_start + page_size]
                query = self.get_dml_builder().build_bulk_insert_query(
                    schema_name=schema_name,
                    table_name=table_name,
                    insert_column_list=column_list,
                    rows=batch,
                    conflict_merge_fields=conflict_merge_fields,
                )
                cursor.execute(query)
            self.connection.commit()
        except Exception as ex:
            self.connection.rollback()
            raise ex
        finally:
            cursor.close()

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
        """Insert rows in batches and return one result per batch.

        Splits table_path into schema and table name, then delegates
        to ``execute_bulk_insert_with_result``.
        """
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
        """Execute a bulk INSERT and return one QueryExecResult per batch.

        Same batching logic as ``execute_bulk_insert`` but each batch
        produces a tracked result with row count and timestamps.

        Args:
            schema_name: target schema name.
            table_name: target table name.
            column_list: columns to insert into.
            rows: list of row tuples to insert.
            conflict_merge_fields: optional list of conflict
                target columns for ON CONFLICT.
            batch_size: number of rows per batch (default 1000).
            technical_tracking_timestamp_columns: optional mapping of column
                name to a raw SQL expression appended to every row (e.g. the
                technical tracking timestamps set to CURRENT_TIMESTAMP).
            exclude_from_update: columns to omit from the ON CONFLICT
                UPDATE SET clause.
            expression_overrides: columns set to a custom SQL expression
                instead of EXCLUDED.col on update.
            exclude_from_match: columns kept in UPDATE SET but excluded from
                the change-detection clause.

        Returns:
            A list of QueryExecResult, one per executed batch.
        """
        cursor = self.get_active_cursor()
        results: list[QueryExecResult] = []
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
                cursor.execute(query)
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
        except Exception as ex:
            self.connection.rollback()
            raise ex
        finally:
            cursor.close()
        return results

    def set_schema_on_connection(self, schema: str) -> QueryExecResult:
        """Set the schema for the connection.

        Args:
            schema: The name of the schema to set.

        Returns:
            The result of the schema setting operation.

        Raises:
            RuntimeError: If the schema cannot be set.
        """
        return self.execute_query(
            query=QueryWrapper(
                query="SET search_path TO {{ schema }}",
                params={"schema": schema},
                runtime_exception_message=f"Schema {schema} cannot be set",
            ),
        )

    # DDL operations

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

    @staticmethod
    def clean_object_path(object_path: str) -> str:
        """Cleans the object path by checking specification compliance.

        Ensures the object path has both schema name and object name only.
        """
        return object_path

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

    def create_or_replace_view(
        self,
        view_path: str,
        sql_query: str,
    ) -> QueryExecResult:
        """Create or replace a PostgreSQL view.

        PostgreSQL's ``CREATE OR REPLACE VIEW`` is append-only: it can add
        columns at the end but cannot drop, rename, reorder, or retype the
        existing ones, raising ``42P16`` (``InvalidTableDefinition``) when the
        new definition is column-incompatible. Other backends replace the view
        wholesale instead, so the flow succeeds there.

        To match that behaviour, drop the view if it exists and recreate it,
        which is the standard way to replace a view on PostgreSQL regardless of
        whether the column set changed. The drop is issued with ``CASCADE`` so
        that views depending on this one are dropped too — PostgreSQL refuses a
        plain ``DROP VIEW`` while dependents exist, and the dependent views are
        expected to be rebuilt by their own VIEW flows.
        """
        view_path = self.clean_object_path(view_path)
        schema_name, view_name = self._split_object_path(view_path)
        self.execute_query(
            query=QueryWrapper(
                query=self.get_ddl_builder().build_drop_view(
                    schema=schema_name,
                    table=view_name,
                    if_exists=True,
                    cascade=True,
                ),
                name=view_path,
            ),
        )
        return self.execute_query(
            query=QueryWrapper(
                query=f"CREATE VIEW {view_path} AS ({sql_query})",
                name=view_path,
            ),
        )

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
                self.drop_table(
                    table_path,
                    if_exists=True,
                )
                self.log_info("Table {table_path} dropped.")
            elif table_exists == "fail":
                raise ValueError(f"Table {table_path} already exists")

        table_path = self.clean_object_path(table_path)
        schema_name, table_name = self._split_object_path(table_path)

        columns = [
            (field.name, field.data_type, False) for field in structure.fields.values()
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
        """Create an index or unique constraint on a table with columns.

        Args:
            index_name: Name of the index or constraint to create.
            table_path: Full path to the table (schema.table or just table).
            columns: List of column names to include in the index/constraint.
            unique: If True, creates a unique index or constraint.
            use_constraint: If True, creates a UNIQUE CONSTRAINT instead of
                INDEX. This is required for ON CONFLICT clauses in upserts.

        Returns:
            Result of the index/constraint creation query.

        Example:
            >>> connector.create_index(
            ...     index_name="idx_user_email",
            ...     table_path="public.users",
            ...     columns=["email"],
            ...     unique=True,
            ...     use_constraint=True,
            ... )
        """
        table_path = self.clean_object_path(table_path)
        schema_name, table_name = self._split_object_path(table_path)

        ddl_builder = self.get_ddl_builder()
        if use_constraint and unique:
            create_sql = ddl_builder.build_alter_add_constraint(
                schema=schema_name,
                table=table_name,
                constraint_name=index_name,
                constraint_type="UNIQUE",
                columns=columns,
            )
        else:
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
        """Insert a single row into a PostgreSQL table.

        Args:
            table_path: fully qualified table path (e.g. schema.table).
            data: mapping of column names to values for the new row.

        Returns:
            The result of the INSERT query execution.
        """
        table_path = self.clean_object_path(table_path)
        schema_name, table_name = self._split_object_path(table_path)
        columns = list(data.keys())
        values = list(data.values())

        table_ref = quote_table(
            schema=schema_name,
            table=table_name,
            dialect=POSTGRES_DIALECT,
        )
        cols = identifier_list(
            columns,
            dialect=POSTGRES_DIALECT,
        )
        vals = literal_list(
            values,
            dialect=POSTGRES_DIALECT,
        )

        insert_query = f"INSERT INTO {table_ref} ({cols}) VALUES ({vals})"
        return self.execute_query(insert_query)

    def upsert_into(
        self,
        table_path: str,
        data: dict[str, Any],
        upsert_fields: list[str],
        **kwargs: Any,
    ) -> QueryExecResult:
        """Insert a row or update it on conflict in PostgreSQL.

        Uses INSERT ... ON CONFLICT DO UPDATE SET to upsert. Columns
        not in the upsert_fields list are updated with the new values.

        Args:
            table_path: fully qualified table path (e.g. schema.table).
            data: mapping of column names to values.
            upsert_fields: columns that form the conflict target.

        Returns:
            The result of the UPSERT query execution.
        """
        table_path = self.clean_object_path(table_path)
        schema_name, table_name = self._split_object_path(table_path)
        columns = list(data.keys())
        values = list(data.values())
        update_fields = [col for col in columns if col not in upsert_fields]

        if not update_fields:
            raise ValueError("No fields to update after excluding upsert_fields")

        table_ref = quote_table(
            schema=schema_name,
            table=table_name,
            dialect=POSTGRES_DIALECT,
        )
        cols = identifier_list(
            columns,
            dialect=POSTGRES_DIALECT,
        )
        vals = literal_list(
            values,
            dialect=POSTGRES_DIALECT,
        )
        conflict_cols = identifier_list(
            upsert_fields,
            dialect=POSTGRES_DIALECT,
        )
        update_set = ", ".join(f"{col} = EXCLUDED.{col}" for col in update_fields)

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
        """Delete rows from a PostgreSQL table matching the conditions.

        Builds a DELETE FROM ... WHERE statement. Multiple conditions
        are combined with AND.

        Args:
            table_path: fully qualified table path (e.g. schema.table).
            where_conditions: mapping of column names to values for
                the WHERE clause.

        Returns:
            The result of the DELETE query execution.
        """
        table_path = self.clean_object_path(table_path)
        schema_name, table_name = self._split_object_path(table_path)

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
            schema=schema_name,
            table=table_name,
            dialect=POSTGRES_DIALECT,
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
        """Insert rows into a PostgreSQL table from a SELECT query.

        Args:
            table_path: fully qualified table path (e.g. schema.table).
            sql_query: the SELECT query providing the data to insert.
            column_list: columns to insert into.

        Returns:
            The result of the INSERT query execution.
        """
        table_path = self.clean_object_path(table_path)
        schema_name, table_name = self._split_object_path(table_path)
        insert_query = self.get_dml_builder().build_insert_from_select_query(
            schema_name=schema_name,
            table_name=table_name,
            selection_query=sql_query,
            insert_column_list=column_list,
        )
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
        """Insert rows from a SELECT query, updating on conflict.

        Uses INSERT INTO ... SELECT ... ON CONFLICT DO UPDATE SET
        to upsert rows from the query result. Columns not in the
        upsert_fields list are updated with the new values.

        Args:
            table_path: fully qualified table path (e.g. schema.table).
            sql_query: the SELECT query providing the data.
            column_list: columns to insert into.
            upsert_fields: columns that form the conflict target.
            exclude_from_update: columns to omit from UPDATE SET.
            expression_overrides: columns to set to custom SQL
                expressions instead of EXCLUDED.col on update.
            exclude_from_match: columns to keep in UPDATE SET but
                exclude from the change-detection clause.

        Returns:
            The result of the UPSERT query execution.
        """
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
            query=QueryWrapper(
                query=upsert_query,
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
        """Delete rows from a PostgreSQL table matching keys from a query.

        Builds a DELETE statement that removes rows where the key
        columns match values returned by the subquery.

        Args:
            table_path: fully qualified table path (e.g. schema.table).
            sql_query: the SELECT query returning key values to delete.
            key_columns: columns used to match rows for deletion.

        Returns:
            The result of the DELETE query execution.
        """
        table_path = self.clean_object_path(table_path)
        schema_name, table_name = self._split_object_path(table_path)

        table_ref = quote_table(
            schema=schema_name,
            table=table_name,
            dialect=POSTGRES_DIALECT,
        )
        key_cols = identifier_list(
            key_columns,
            dialect=POSTGRES_DIALECT,
        )

        delete_query = (
            f"DELETE FROM {table_ref} "
            f"WHERE ({key_cols}) IN (SELECT {key_cols} FROM ({sql_query}) AS _subq)"
        )
        return self.execute_query(
            query=QueryWrapper(
                query=delete_query,
                name=table_path,
            ),
        )

    def _split_object_path(self, object_path: str) -> tuple[str, str]:
        """Split a qualified object path into schema and object name."""
        if "." in object_path:
            schema_name, table_name = object_path.split(".", maxsplit=1)
            return schema_name, table_name
        return self.get_active_schema() or "public", object_path
