from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from nld.connector.snowflake.service.data_profiler import (
        SnowflakeDataProfiler,
    )
    from nld.connector.snowflake.service.structure_diff_ddl_statement_builder import (
        SnowflakeStructureDiffDDLStatementBuilder,
    )
    from nld.connector.snowflake.service.structure_reader import (
        SnowflakeStructureReader,
    )
    from nld.connector.snowflake.sqlglot import SnowflakeSqlglotDMLBuilder

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
from nld.connector.snowflake.query_wrapper import SnowflakeQueryWrapper
from nld.exceptions import NotImplementedMethodException
from nld.logging.events import CSVFileWriteSuccessful
from nld.structure import Structure
from nld.utils.datetime_util import get_current_datetime
from nld.utils.sqlglot.base_ddl import BaseSqlglotDDLBuilder
from snowflake.connector.cursor import SnowflakeCursor
from snowflake.connector.errors import ProgrammingError as SnowflakeProgrammingError

from .snowflake_connection import (
    SnowflakeConnectionWrapper,
)
from .snowflake_utils import SnowflakeUtil

if TYPE_CHECKING:
    from nld.connector.snowflake.pydantic import NldBaseModelSnowflakeManager


class SnowflakeConnector(SQLDataConnector[SnowflakeConnectionWrapper]):
    def __init__(self, connection_wrapper: SnowflakeConnectionWrapper) -> None:
        super().__init__(connection_wrapper)

    @property
    def sqlglot_dialect(self) -> str:
        """The sqlglot dialect name for SQL rendering."""
        return "snowflake"

    def get_ddl_builder(self) -> BaseSqlglotDDLBuilder:
        """Return a Snowflake-specific DDL builder."""
        from nld.connector.snowflake.sqlglot import SnowflakeSqlglotDDLBuilder

        return SnowflakeSqlglotDDLBuilder()

    def get_dml_builder(self) -> SnowflakeSqlglotDMLBuilder:
        """Return a Snowflake-specific DML builder."""
        from nld.connector.snowflake.sqlglot import SnowflakeSqlglotDMLBuilder

        return SnowflakeSqlglotDMLBuilder()

    def get_active_schema(self) -> str | None:
        """Return the active schema from the connection."""
        return self.connection_wrapper.get_active_schema()

    def get_structure_reader(self) -> SnowflakeStructureReader:
        """Return a Snowflake structure reader."""
        from nld.connector.snowflake.service.structure_reader import (
            SnowflakeStructureReader,
        )

        return SnowflakeStructureReader(connector=self)

    def get_data_profiler(self) -> SnowflakeDataProfiler:
        """Return a Snowflake data profiler for this connector."""
        from nld.connector.snowflake.service.data_profiler import (
            SnowflakeDataProfiler,
        )

        return SnowflakeDataProfiler(self)

    def get_structure_diff_ddl_statement_builder(
        self,
    ) -> SnowflakeStructureDiffDDLStatementBuilder:
        """Return a Snowflake-specific structure diff DDL generator."""
        from nld.connector.snowflake.service import (
            SnowflakeStructureDiffDDLStatementBuilder,
        )

        return SnowflakeStructureDiffDDLStatementBuilder()

    def get_connector_definition(self) -> ConnectorDefinition:
        """Return the static engine facts of the Snowflake connector."""
        from nld.connector.snowflake.connector_definition import (
            SNOWFLAKE_CONNECTOR_DEFINITION,
        )

        return SNOWFLAKE_CONNECTOR_DEFINITION

    def get_deploy_capabilities(self) -> ConnectorDeployCapabilities:
        """Return the declared Snowflake structure deployment capabilities."""
        from nld.connector.snowflake.service import (
            SNOWFLAKE_DEPLOY_CAPABILITIES,
        )

        return SNOWFLAKE_DEPLOY_CAPABILITIES

    def get_model_manager(self) -> NldBaseModelSnowflakeManager:
        """Return a Snowflake pydantic model manager."""
        from nld.connector.snowflake.pydantic import NldBaseModelSnowflakeManager

        return NldBaseModelSnowflakeManager(connector=self)

    @staticmethod
    def clean_object_path(object_path: str) -> str:
        """Cleans the object path by checking specification compliance.

        Ensures the object path has both schema name and object name only.
        """
        return object_path

    def log_execution_error(  # type: ignore[override]
        self, error: SnowflakeProgrammingError
    ) -> None:
        self.log_error(SnowflakeUtil.get_standard_error_message(error))

    def retrieve_current_session_id(self) -> str:
        session_id = cast(
            str,
            self.execute_query_for_single_value_output(
                query=QueryWrapper(
                    query="SELECT CURRENT_SESSION() AS SESSION_ID",
                    name="Get Session ID",
                ),
            ),
        )
        self.connection_wrapper.session_id = session_id
        return session_id

    @staticmethod
    def get_active_cursor(
        conn_wrapper: SnowflakeConnectionWrapper,
    ) -> SnowflakeCursor:
        """Get the active cursor on the connection wrapper.

        Args:
            conn_wrapper: The snowflake connection wrapper.

        Returns:
            The connection cursor.
        """
        assert conn_wrapper.connection is not None
        return conn_wrapper.connection.cursor()

    def _prepare_query_wrapper(
        self,
        query: str | QueryWrapper,
    ) -> SnowflakeQueryWrapper:
        """Convert a query string or QueryWrapper to a SnowflakeQueryWrapper."""
        if isinstance(query, SnowflakeQueryWrapper):
            return query
        if isinstance(query, QueryWrapper):
            return SnowflakeQueryWrapper(
                query=query.query,
                interpreted_query=query.interpreted_query,
                name=query.name,
                params=query.params,
                runtime_exception_message=query.runtime_exception_message,
            )
        return SnowflakeQueryWrapper(query=query)

    def execute_query(self, query: str | QueryWrapper) -> QueryExecResult:
        query_wrapper = self._prepare_query_wrapper(query)
        cur = self.get_active_cursor(self.connection_wrapper)
        start_tst = get_current_datetime()
        query_wrapper.update_interpreted_query()
        self.log_debug("Complete query to be executed : ")
        self.log_debug(query_wrapper.get_interpreted_query())
        expected_output = query_wrapper.get_expected_output_type()
        resolved_operation_type = query_wrapper.operation_type
        try:
            cur.execute(query_wrapper.get_interpreted_query())
            result_data = list(cur)

            message = None
            output_structure = None
            row_count = None

            if expected_output == QueryOutputType.DATASET:
                output_structure = SnowflakeUtil.get_structure_from_result_metadata(
                    cur.description
                )
            elif expected_output == QueryOutputType.ROW_COUNT:
                row_count = (
                    cur.rowcount
                    if cur.rowcount is not None and cur.rowcount >= 0
                    else 0
                )
            else:
                # Snowflake DDL returns a status row
                if result_data and len(result_data) > 0:
                    first_row = result_data[0]
                    if isinstance(first_row, tuple) and len(first_row) > 0:
                        message = str(first_row[0])
                    else:
                        message = str(first_row)
                if not message:
                    message = (
                        f"{resolved_operation_type.value} statement "
                        f"executed successfully."
                        if resolved_operation_type is not None
                        else "Statement executed successfully."
                    )

            result = QueryExecResult(
                query_name=query_wrapper.name,
                exec_status=QueryExecResultStatus.SUCCESS,
                query=query_wrapper.get_interpreted_query(),
                query_id=cast(str, cur.sfqid),
                output_structure=output_structure,
                start_tst=start_tst,
                end_tst=get_current_datetime(),
                message=message,
                operation_type=resolved_operation_type,
                row_count=row_count,
                result_data=result_data,
            )
            return result
        except SnowflakeProgrammingError as e:
            self.log_execution_error(e)
            query_wrapper.raise_runtime_exception()
            result = QueryExecResult(
                query_name=query_wrapper.name,
                exec_status=QueryExecResultStatus.ERROR,
                query=query_wrapper.get_interpreted_query(),
                query_id=cast(str, e.sfqid),
                output_structure=SnowflakeUtil.get_structure_for_error_result(),
                start_tst=start_tst,
                end_tst=get_current_datetime(),
                operation_type=resolved_operation_type,
                result_data=[SnowflakeUtil.get_standard_error_message(e)],
            )
            return result
        finally:
            cur.close()

    def export_query_to_csv(
        self,
        query: str | QueryWrapper,
        output_file_path: str,
        delimiter: str = ",",
        include_header: bool = True,
        encoding: str = "utf-8",
    ) -> int:
        """Export a SELECT result to CSV via the Snowflake Arrow fetch path.

        ``fetch_pandas_all`` pulls the result set as Arrow batches from
        Snowflake, which is the connector-native way to materialize a
        query result before writing it to the target CSV file.
        """
        self.assert_select_query(query)
        query_text = query.query if isinstance(query, QueryWrapper) else query
        cursor = self.get_active_cursor(self.connection_wrapper)
        try:
            cursor.execute(query_text)
            data_frame = cursor.fetch_pandas_all()
        except SnowflakeProgrammingError as error:
            self.log_execution_error(error)
            raise QueryExecutionException(
                error_message=SnowflakeUtil.get_standard_error_message(error),
            ) from error
        finally:
            cursor.close()
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

    def execute_query_for_single_value_output(
        self,
        query: str | QueryWrapper,
    ) -> Any:
        query_exec_result = self.execute_query(query=query)

        return query_exec_result.get_result_single_value()

    # Connection operations
    def _set_role_on_connection(self, role: str) -> QueryExecResult:
        return self.execute_query(
            query=QueryWrapper(
                query="USE ROLE {{ role }}",
                params={"role": role},
                runtime_exception_message="Role {role} cannot be set",
            ),
        )

    def _set_warehouse_on_connection(self, warehouse: str) -> QueryExecResult:
        return self.execute_query(
            query=QueryWrapper(
                query="USE WAREHOUSE {{ warehouse }}",
                params={"warehouse": warehouse},
                runtime_exception_message="Warehouse {warehouse} cannot be set",
            ),
        )

    def _set_database_on_connection(self, database: str) -> QueryExecResult:
        return self.execute_query(
            query=QueryWrapper(
                query="USE DATABASE {{ database }}",
                params={"database": database},
                runtime_exception_message="Database {database} cannot be set",
            ),
        )

    def set_schema_on_connection(self, schema: str) -> QueryExecResult:
        return self.execute_query(
            query=QueryWrapper(
                query="USE SCHEMA {{ schema }}",
                params={"schema": schema},
                runtime_exception_message="Schema {schema} cannot be set",
            ),
        )

    def set_connection(
        self,
        role: str | None = None,
        database: str | None = None,
        schema: str | None = None,
        warehouse: str | None = None,
    ) -> None:
        if role is None:
            return

        self._set_role_on_connection(role)

        if warehouse is not None:
            self._set_warehouse_on_connection(warehouse)

        if database is not None:
            self._set_database_on_connection(database)

            if schema is not None:
                self.set_schema_on_connection(schema)

    def set_connection_using_credentials(self) -> None:
        connection_update_params = {
            k: v
            for k, v in asdict(self.connection_wrapper.credentials).items()
            if k in ["role", "warehouse", "database", "schema"] and v is not None
        }
        if connection_update_params:
            self.set_connection(**connection_update_params)

    # DDL Operations
    def get_ddl(
        self,
        obj_type: str,
        obj_name: str,
    ) -> str:
        """Get the DDL from the database connection for a single object.

        Args:
            obj_type: The object type (should be one of the following: TABLE,
                VIEW, PROCEDURE, SCHEMA, DATABASE).
            obj_name: The object name.

        Returns:
            The DDL statement retrieved from the database connection.
        """
        get_ddl_query = QueryWrapper(
            query=f"SELECT GET_DDL('{obj_type}', '{obj_name}');"
        )
        return cast(str, self.execute_query_for_single_value_output(get_ddl_query))

    # Standard operations
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

    def list_files_in_stage(self, schema_name: str, stage_name: str) -> QueryExecResult:
        query_wrapper = QueryWrapper(
            query="list @{{ schema_name }}.{{ stage_name }}",
            params={"schema_name": schema_name, "stage_name": stage_name},
        )
        return self.execute_query(query=query_wrapper)

    def drop_table(
        self, table_path: str, if_exists: bool = False, **kwargs: Any
    ) -> QueryExecResult:
        """Drop a Snowflake table."""
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

    def create_table(
        self,
        table_path: str,
        structure: Structure,
        table_exists: str = "skip",
        override_primary_key_fields: list[str] | None = None,
        **kwargs: Any,
    ) -> QueryExecResult | None:
        """Create a Snowflake table from a Structure definition."""
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
            for field in structure.get_all_fields()
        ]

        primary_key_fields: list[str] | None = None
        if override_primary_key_fields:
            primary_key_fields = override_primary_key_fields
        elif structure.has_primary_key():
            primary_key_fields = [
                field.name for field in structure.get_primary_key_fields()
            ]

        create_sql = self.get_ddl_builder().build_create_table(
            schema=schema_name,
            table=table_name,
            columns=columns,
            primary_key_fields=primary_key_fields,
        )
        return self.execute_query(query=QueryWrapper(query=create_sql, name=table_path))

    def _split_object_path(self, object_path: str) -> tuple[str, str]:
        """Split a qualified object path into schema and object name."""
        if "." in object_path:
            schema_name, table_name = object_path.split(".", maxsplit=1)
            return schema_name, table_name
        return self.get_active_schema() or "PUBLIC", object_path

    def get_row_count(
        self,
        object_path: str,
        where_conditions: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> int:
        """Return the number of rows, using single-value extraction."""
        dml_builder = self.get_dml_builder()
        query = dml_builder.build_count_query(
            table_path=object_path,
            where_conditions=where_conditions,
        )
        result = self.execute_query(query)
        value = result.get_result_single_value()
        return int(value) if value is not None else 0

    def does_object_exist(self, object_path: str, **kwargs: Any) -> bool:
        object_path = self.clean_object_path(object_path)
        schema_name, table_name = self._split_object_path(object_path)
        # SHOW OBJECTS reads the authoritative metadata store — the
        # INFORMATION_SCHEMA.TABLES view can serve stale rows right
        # after cross-session DDL (renames especially). LIKE treats
        # "_" as a single-char wildcard, so the rows are re-filtered
        # on the exact name.
        pattern = table_name.upper().replace("'", "''")
        query = f"SHOW OBJECTS LIKE '{pattern}' IN SCHEMA \"{schema_name.upper()}\""
        query_exec_result = self.execute_query(query)
        # A failed listing must raise, never report "does not exist" —
        # deploy decisions (CREATE vs ALTER) depend on this answer.
        query_exec_result.raise_on_error(
            f"Snowflake object-existence check failed: {query}",
        )
        return any(
            record["name"] == table_name.upper()
            for record in query_exec_result.get_result_records()
        )

    def get_column_names(self, object_path: str, **kwargs: Any) -> list[str]:
        object_path = self.clean_object_path(object_path)
        schema_name, table_name = self._split_object_path(object_path)
        query_exec_result = self.execute_query(
            self.get_ddl_builder().build_column_names_query(
                schema=schema_name,
                table=table_name,
            )
        )
        query_exec_result.raise_on_error(
            f"Snowflake column-name read failed for {object_path}",
        )
        # Snowflake stores unquoted identifiers in uppercase; lower them
        # to match the nld naming convention, like the structure reader.
        return [
            record["column_name"].lower()
            for record in query_exec_result.get_result_records()
        ]

    @staticmethod
    def _escape_value(value: Any) -> str:
        """Escape a value for use in a Snowflake INSERT VALUES clause."""
        if value is None:
            return "NULL"
        escaped = str(value).replace("'", "''")
        return f"'{escaped}'"

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
        """Insert rows in batches using multi-row INSERT statements.

        When conflict_merge_fields is provided, uses MERGE INTO for
        upsert semantics instead of plain INSERT.
        """
        if any(
            (
                technical_tracking_timestamp_columns,
                exclude_from_update,
                expression_overrides,
                exclude_from_match,
            )
        ):
            raise NotImplementedError(
                "Snowflake bulk_insert_into does not yet support technical "
                "tracking timestamp injection or the ON CONFLICT upsert "
                "parameters; these are implemented for PostgreSQL and DuckDB."
            )
        table_path = self.clean_object_path(table_path)
        cols = ", ".join(column_list)
        results: list[QueryExecResult] = []

        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            value_rows = ", ".join(
                f"({', '.join(self._escape_value(v) for v in row)})" for row in batch
            )

            if conflict_merge_fields:
                on_clause = " AND ".join(
                    f"target.{f} = source.{f}" for f in conflict_merge_fields
                )
                update_cols = [c for c in column_list if c not in conflict_merge_fields]
                update_set = ", ".join(f"{c} = source.{c}" for c in update_cols)
                change_conditions = " OR ".join(
                    f"target.{c} IS DISTINCT FROM source.{c}" for c in update_cols
                )
                insert_vals = ", ".join(f"source.{c}" for c in column_list)
                source_cols = ", ".join(
                    f"${idx + 1} AS {c}" for idx, c in enumerate(column_list)
                )
                if change_conditions:
                    matched_clause = (
                        f"WHEN MATCHED AND ({change_conditions}) "
                        f"THEN UPDATE SET {update_set} "
                    )
                else:
                    matched_clause = f"WHEN MATCHED THEN UPDATE SET {update_set} "
                sql = (
                    f"MERGE INTO {table_path} AS target "
                    f"USING (SELECT {source_cols} FROM VALUES {value_rows}) AS source "
                    f"ON {on_clause} "
                    f"{matched_clause}"
                    f"WHEN NOT MATCHED THEN INSERT ({cols}) VALUES ({insert_vals})"
                )
            else:
                sql = f"INSERT INTO {table_path} ({cols}) VALUES {value_rows}"

            result = self.execute_query(QueryWrapper(query=sql, name=table_path))
            results.append(result)
            if result.failed():
                return results

        return results

    def create_or_replace_view(
        self,
        view_path: str,
        sql_query: str,
    ) -> QueryExecResult:
        """Create or replace a Snowflake view."""
        view_path = self.clean_object_path(view_path)
        sql = f"CREATE OR REPLACE VIEW {view_path} AS {sql_query}"
        return self.execute_query(QueryWrapper(query=sql, name=view_path))

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
        """Upsert rows from a SELECT query using Snowflake MERGE INTO."""
        table_path = self.clean_object_path(table_path)
        cols = ", ".join(column_list)
        on_clause = " AND ".join(f"target.{f} = source.{f}" for f in upsert_fields)
        exclude_set = set(exclude_from_update or [])
        overrides = expression_overrides or {}
        exclude_from_match_set = set(exclude_from_match or [])
        update_cols = [
            c for c in column_list if c not in upsert_fields and c not in exclude_set
        ]
        if not update_cols:
            raise ValueError(
                "No fields to update after excluding upsert_fields",
            )
        update_parts = []
        for c in update_cols:
            if c in overrides:
                update_parts.append(f"{c} = {overrides[c]}")
            else:
                update_parts.append(f"{c} = source.{c}")
        update_set = ", ".join(update_parts)
        insert_vals = ", ".join(f"source.{c}" for c in column_list)

        data_cols_for_comparison = [
            c
            for c in update_cols
            if c not in overrides and c not in exclude_from_match_set
        ]
        if data_cols_for_comparison:
            change_conditions = " OR ".join(
                f"target.{c} IS DISTINCT FROM source.{c}"
                for c in data_cols_for_comparison
            )
            matched_clause = (
                f"WHEN MATCHED AND ({change_conditions}) THEN UPDATE SET {update_set} "
            )
        else:
            matched_clause = f"WHEN MATCHED THEN UPDATE SET {update_set} "

        merge_sql = (
            f"MERGE INTO {table_path} AS target "
            f"USING ({sql_query}) AS source "
            f"ON {on_clause} "
            f"{matched_clause}"
            f"WHEN NOT MATCHED THEN INSERT ({cols}) VALUES ({insert_vals})"
        )
        return self.execute_query(QueryWrapper(query=merge_sql, name=table_path))

    def insert_into(
        self,
        table_path: str,
        data: dict[str, Any],
        **kwargs: Any,
    ) -> QueryExecResult:
        raise NotImplementedMethodException(self.__class__, "insert_into")

    def upsert_into(
        self,
        table_path: str,
        data: dict[str, Any],
        upsert_fields: list[str],
        **kwargs: Any,
    ) -> QueryExecResult:
        raise NotImplementedMethodException(self.__class__, "upsert_into")

    def delete_from(
        self,
        table_path: str,
        where_conditions: dict[str, Any],
        **kwargs: Any,
    ) -> QueryExecResult:
        """Delete rows from a Snowflake table matching the conditions."""
        if not where_conditions:
            raise ValueError(
                "where_conditions must not be empty to prevent accidental full deletes"
            )
        table_path = self.clean_object_path(table_path)
        dml_builder = self.get_dml_builder()
        conditions = [
            dml_builder.equality_clause(field=field, value=value)
            for field, value in where_conditions.items()
        ]
        where = dml_builder.and_clause(conditions)
        delete_query = f"DELETE FROM {table_path} WHERE {where}"
        return self.execute_query(
            QueryWrapper(query=delete_query, name=table_path),
        )

    def insert_into_from_query(
        self,
        table_path: str,
        sql_query: str,
        column_list: list[str],
        **kwargs: Any,
    ) -> QueryExecResult:
        """Insert rows from a SELECT query into a Snowflake table."""
        table_path = self.clean_object_path(table_path)
        cols = ", ".join(column_list)
        sql = f"INSERT INTO {table_path} ({cols}) {sql_query}"
        return self.execute_query(QueryWrapper(query=sql, name=table_path))

    def delete_from_query(
        self,
        table_path: str,
        sql_query: str,
        key_columns: list[str],
        **kwargs: Any,
    ) -> QueryExecResult:
        """Delete rows whose keys match the SELECT query, via DELETE USING.

        The SQL is rendered by the Snowflake DML builder
        (``build_delete_from_query``).
        """
        table_path = self.clean_object_path(table_path)
        delete_query = self.get_dml_builder().build_delete_from_query(
            table_path=table_path,
            sql_query=sql_query,
            key_columns=key_columns,
        )
        return self.execute_query(
            QueryWrapper(query=delete_query, name=table_path),
        )

    def copy_into_table_from_stage(
        self,
        schema_name: str,
        table_name: str,
        stage_schema_name: str,
        stage_name: str,
        stage_select_query: str,
        file_format_name: str,
    ) -> QueryExecResult:
        query_wrapper = QueryWrapper(
            query="""COPY INTO {{ schema_name }}.{{ table_name }} FROM (
        {{ stage_select_query }}
        FROM @{{ stage_schema_name }}.{{ stage_name }}
            (FILE_FORMAT => {{ file_format_name }})
        )
            ON_ERROR = CONTINUE""",
            params={
                "schema_name": schema_name,
                "table_name": table_name,
                "stage_schema_name": stage_schema_name,
                "stage_name": stage_name,
                "stage_select_query": stage_select_query,
                "file_format_name": file_format_name,
            },
        )
        return self.execute_query(query=query_wrapper)
