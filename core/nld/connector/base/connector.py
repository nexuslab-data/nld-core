from __future__ import annotations

import abc
from collections.abc import Iterable
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from nld.exceptions import NotImplementedMethodException
from nld.structure import Structure
from nld.utils.mixin import NldMixIn
from nld.utils.sqlglot import get_query_statement_type, is_select_query
from nld.utils.sqlglot.base_ddl import BaseSqlglotDDLBuilder
from nld.utils.sqlglot.base_dml import BaseSqlglotDMLBuilder

from .connection import ConnectionWrapper
from .connector_definition import ConnectorDefinition
from .deploy_capabilities import ConnectorDeployCapabilities
from .exceptions import (
    NonSelectQueryException,
    SingleValueResultException,
)
from .query import QueryExecResult, QueryWrapper

if TYPE_CHECKING:
    from nld.pydantic.backend.base_model_manager import NldBaseModelManager
    from nld.structure.deploy.structure_diff_ddl_statement_builder import (
        BaseStructureDiffDDLStatementBuilder,
    )

    from .data_profiler import ConnectorDataProfiler
    from .structure_reader import ConnectorStructureReader


class DataConnector[CONNECTION_WRAPPER: ConnectionWrapper[Any, Any]](NldMixIn):
    def __init__(
        self,
        connection_wrapper: CONNECTION_WRAPPER,
    ) -> None:
        super().__init__()
        self.connection_wrapper = connection_wrapper

    def assert_connection_is_opened(self) -> None:
        assert self.connection_wrapper is not None
        assert self.connection_wrapper.connection is not None
        if not self.connection_is_opened():
            message = (
                f"{self.connection_wrapper.type} connection "
                f"with name: {self.connection_wrapper.name} is not opened"
            )
            self.log_debug(message)
            raise RuntimeError(message)

    def connection_is_opened(self) -> bool:
        if self.connection_wrapper is None:
            return False
        if self.connection_wrapper.connection is None:
            return False
        return self.connection_wrapper.is_opened()

    def open_connection(self) -> bool:
        if self.connection_wrapper is None:
            return False
        if self.connection_wrapper.is_opened():
            return True
        self.connection_wrapper.open()
        return self.connection_wrapper.is_opened()

    def close_connection(self) -> bool:
        if self.connection_wrapper is None:
            return False
        if self.connection_wrapper.is_closed():
            return True
        self.connection_wrapper.close()
        return self.connection_wrapper.is_closed()

    def get_structure_reader(self) -> ConnectorStructureReader[Any]:
        """Return a structure reader for this connector.

        Subclasses that support structure extraction must override
        this method to return the appropriate reader instance.
        """
        raise NotImplementedMethodException(
            self.__class__,
            "get_structure_reader",
        )

    def supports_data_profiling(self) -> bool:
        """Whether this connector's engine can profile/audit table data.

        False on the base connector; SQL connectors override it. Callers can
        check this before requesting a profiler to give a clean error for
        engines (e.g. blob storage) that cannot measure data.
        """
        return False

    def get_data_profiler(self) -> ConnectorDataProfiler[Any]:
        """Return a data profiler for this connector.

        Only connectors whose engine can measure data override this; the base
        connector raises, so profiling is an opt-in per-engine capability.
        """
        raise NotImplementedMethodException(
            self.__class__,
            "get_data_profiler",
        )

    def get_ddl_builder(self) -> BaseSqlglotDDLBuilder:
        """Return a DDL builder for this connector's dialect.

        Subclasses should override this method to return a
        connector-specific DDL builder when dialect-specific SQL
        syntax is needed.
        """
        raise NotImplementedMethodException(
            self.__class__,
            "get_ddl_builder",
        )

    def get_structure_diff_ddl_statement_builder(
        self,
    ) -> BaseStructureDiffDDLStatementBuilder:
        """Return a DDL generator for structure deployment.

        Subclasses that support structure deployment must override
        this method to return the appropriate generator instance.
        """
        raise NotImplementedMethodException(
            self.__class__,
            "get_structure_diff_ddl_statement_builder",
        )

    def get_connector_definition(self) -> ConnectorDefinition:
        """Return the static engine facts of this connector.

        Subclasses must override this method to return their declared
        definition — the models and services consult it instead of
        hardcoding engine knowledge locally.
        """
        raise NotImplementedMethodException(
            self.__class__,
            "get_connector_definition",
        )

    def get_deploy_capabilities(self) -> ConnectorDeployCapabilities:
        """Return what this engine supports for structure deployment.

        Subclasses that support structure deployment must override
        this method to return their declared capability profile — an
        engine whose behavior was never assessed must not deploy.
        """
        raise NotImplementedMethodException(
            self.__class__,
            "get_deploy_capabilities",
        )

    def get_dml_builder(self) -> BaseSqlglotDMLBuilder:
        """Return a DML builder for this connector's dialect.

        Subclasses should override this method to return a
        connector-specific DML builder when dialect-specific SQL
        syntax is needed.
        """
        raise NotImplementedMethodException(
            self.__class__,
            "get_dml_builder",
        )

    def get_active_schema(self) -> str | None:
        """Return the active schema for the connection.

        Subclasses should override this method to return the
        schema configured on the connection credentials.
        """
        raise NotImplementedMethodException(
            self.__class__,
            "get_active_schema",
        )

    def get_model_manager(self) -> NldBaseModelManager:
        """Return a pydantic model manager for this connector.

        Subclasses should override this method to return the
        appropriate NldBaseModelManager implementation for their
        database backend.
        """
        raise NotImplementedMethodException(
            self.__class__,
            "get_model_manager",
        )


class DataTransformationOperation(Enum):
    """Supported DML transformation operations for execute_transfo."""

    DELETE = "delete"
    INSERT = "insert"
    UPSERT = "upsert"


class SQLDataConnector[CONNECTION_WRAPPER: ConnectionWrapper[Any, Any]](
    DataConnector[CONNECTION_WRAPPER], abc.ABC
):
    def __init__(self, connection_wrapper: CONNECTION_WRAPPER) -> None:
        super().__init__(connection_wrapper)

    @property
    def sqlglot_dialect(self) -> str:
        """The sqlglot dialect name for SQL rendering."""
        raise NotImplementedMethodException(
            self.__class__,
            "sqlglot_dialect",
        )

    def supports_data_profiling(self) -> bool:
        """SQL engines can profile data via aggregate queries."""
        return True

    def commit(self) -> None:
        """Commit the engine's current transaction, when it has one.

        Commit ownership lives on the connector: callers must never
        reach into the connection wrapper. The default commits through
        the underlying connection when it exposes a commit and does
        nothing otherwise (engines without a transaction concept, or
        whose ``execute_query`` already commits per statement).
        """
        connection = getattr(self.connection_wrapper, "connection", None)
        if connection is not None and hasattr(connection, "commit"):
            connection.commit()

    def get_data_profiler(self) -> ConnectorDataProfiler[Any]:
        """Return the SQL data profiler, which builds its queries via the
        connector's dialect DML builder and runs them with ``execute_query``."""
        from .data_profiler import SQLConnectorDataProfiler

        return SQLConnectorDataProfiler(self)

    def get_ddl_builder(self) -> BaseSqlglotDDLBuilder:
        """Return a DDL builder for this connector's dialect.

        Subclasses should override this method to return a
        connector-specific DDL builder when dialect-specific SQL
        syntax is needed.
        """
        return BaseSqlglotDDLBuilder(dialect=self.sqlglot_dialect)

    def get_dml_builder(self) -> BaseSqlglotDMLBuilder:
        """Return a DML builder for this connector's dialect.

        Subclasses should override this method to return a
        connector-specific DML builder when dialect-specific SQL
        syntax is needed.
        """
        return BaseSqlglotDMLBuilder(dialect=self.sqlglot_dialect)

    def log_execution_error(self, **kwargs: Any) -> None:
        raise NotImplementedMethodException(self.__class__, "log_execution_error")

    def execute_query(self, query: str | QueryWrapper) -> QueryExecResult:
        raise NotImplementedMethodException(self.__class__, "execute_query")

    @staticmethod
    def clean_object_path(object_path: str) -> str:
        """Normalize an object path for this engine.

        The default is an identity transform; concrete connectors
        override it with their own path-normalization rules.
        """
        return object_path

    # Read-only export operations

    def assert_select_query(self, query: str | QueryWrapper) -> None:
        """Raise when the query is not a read-only SELECT statement.

        Used by per-connector CSV exporters so a read-only export cannot
        mutate the connected database.
        """
        query_text = query.query if isinstance(query, QueryWrapper) else query
        if not is_select_query(query_text, dialect=self.sqlglot_dialect):
            raise NonSelectQueryException(
                query_type=get_query_statement_type(
                    query_text,
                    dialect=self.sqlglot_dialect,
                ),
            )

    @abc.abstractmethod
    def export_query_to_csv(
        self,
        query: str | QueryWrapper,
        output_file_path: str,
        delimiter: str = ",",
        include_header: bool = True,
        encoding: str = "utf-8",
    ) -> int:
        """Execute a SELECT query and export its result to a CSV file.

        Only read-only SELECT (or WITH) statements are accepted so the
        operation cannot mutate the connected database. Each connector
        implements this using its native dependency export path (e.g.
        psycopg2 ``COPY`` for PostgreSQL) for efficiency.

        Args:
            query: the SELECT query to execute.
            output_file_path: path of the CSV file to write.
            delimiter: field delimiter for the CSV output.
            include_header: when True, writes a header row with column names.
            encoding: text encoding of the CSV file.

        Returns:
            The number of data rows written to the CSV file.

        Raises:
            NonSelectQueryException: when the query is not a SELECT statement.
            QueryExecutionException: when the query execution fails.
        """
        raise NotImplementedMethodException(self.__class__, "export_query_to_csv")

    # DDL operations

    @abc.abstractmethod
    def drop_table(
        self,
        table_path: str,
        if_exists: bool = False,
        **kwargs: Any,
    ) -> QueryExecResult:
        """Drop a table from the database.

        Generates and executes a DROP TABLE statement. When
        ``if_exists`` is True, appends IF EXISTS to prevent errors
        when the table is already absent.

        Args:
            table_path: fully qualified table path (e.g. schema.table).
            if_exists: when True, adds IF EXISTS to the statement.

        Returns:
            The result of the DROP TABLE query execution.
        """
        raise NotImplementedMethodException(self.__class__, "drop_table")

    @abc.abstractmethod
    def create_table(
        self,
        table_path: str,
        structure: Structure,
        table_exists: str = "skip",
        **kwargs: Any,
    ) -> QueryExecResult | None:
        """Create a table in the database from a Structure definition.

        Builds a CREATE TABLE statement by iterating over the fields
        of the provided Structure to produce column definitions and
        an optional PRIMARY KEY clause. The ``table_exists`` parameter
        controls behavior when the table already exists.

        Args:
            table_path: fully qualified table path (e.g. schema.table).
            structure: the Structure object describing columns and types.
            table_exists: action when the table already exists. One of
                "skip" (do nothing), "replace" (drop and recreate),
                or "fail" (raise an error). Defaults to "skip".

        Returns:
            The result of the CREATE TABLE query execution, or None when
            the table already existed and was skipped.
        """
        raise NotImplementedMethodException(self.__class__, "create_table")

    def create_table_as(
        self,
        table_path: str,
        sql_query: str,
    ) -> QueryExecResult:
        """Create a table from a SELECT query (CTAS).

        Args:
            table_path: fully qualified table path (e.g. schema.table)
            sql_query: the SELECT query whose result populates the table

        Returns:
            The result of the CREATE TABLE AS query execution.
        """
        create_query = QueryWrapper(
            query=f"CREATE TABLE {table_path} AS ({sql_query})",
            name=table_path,
        )
        return self.execute_query(query=create_query)

    @abc.abstractmethod
    def truncate_table(self, table_path: str, **kwargs: Any) -> QueryExecResult:
        """Remove all rows from a table without dropping it.

        Generates and executes a TRUNCATE TABLE statement. This is
        faster than DELETE for removing all rows because it does not
        generate individual row-level undo information.

        Args:
            table_path: fully qualified table path (e.g. schema.table).

        Returns:
            The result of the TRUNCATE TABLE query execution.
        """
        raise NotImplementedMethodException(self.__class__, "truncate_table")

    @abc.abstractmethod
    def does_object_exist(self, object_path: str, **kwargs: Any) -> bool:
        """Check whether a database object (table or view) exists.

        Queries the database metadata catalog to determine whether
        the given object is present. Implementations typically query
        information_schema or equivalent system tables.

        Args:
            object_path: fully qualified object path (e.g. schema.table).

        Returns:
            True if the object exists, False otherwise.
        """
        raise NotImplementedMethodException(self.__class__, "does_object_exist")

    def does_schema_exist(self, schema: str, **kwargs: Any) -> bool:
        """Check whether a schema (or dataset) exists.

        Default implementation queries the metadata catalog through
        the dialect DDL builder. Connectors with a dedicated metadata
        API (e.g. BigQuery datasets) should override this.

        Args:
            schema: the schema name.

        Returns:
            True if the schema exists, False otherwise.
        """
        result = self.execute_query(
            self.get_ddl_builder().build_schema_exists_query(schema=schema),
        )
        try:
            return bool(result.get_result_single_value())
        except SingleValueResultException:
            return False

    @abc.abstractmethod
    def get_column_names(self, object_path: str, **kwargs: Any) -> list[str]:
        """Return a table's column names in physical order.

        Queries the database metadata catalog for the columns of the
        given object. Implementations typically query
        information_schema or equivalent system tables.

        Args:
            object_path: fully qualified object path (e.g. schema.table).

        Returns:
            The column names, ordered by ordinal position.
        """
        raise NotImplementedMethodException(self.__class__, "get_column_names")

    def get_row_count(
        self,
        object_path: str,
        where_conditions: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> int:
        """Return the number of rows in a table, optionally filtered.

        Executes a ``SELECT COUNT(*)`` query against the given table.
        When ``where_conditions`` are provided, they are combined with
        AND in a WHERE clause.

        Args:
            object_path: fully qualified table path (e.g. schema.table).
            where_conditions: optional mapping of column names to values
                for filtering.

        Returns:
            The row count as an integer.
        """
        dml_builder = self.get_dml_builder()
        query = dml_builder.build_count_query(
            table_path=object_path,
            where_conditions=where_conditions,
        )
        result = self.execute_query(query)
        # get_result_records handles every engine's row shape (dict,
        # zipped, tuple) — never reach into the private result data
        # assuming dict rows.
        records = result.get_result_records()
        if records:
            return int(records[0].get("row_count", 0))
        return 0

    def has_one_row(
        self,
        object_path: str,
        where_conditions: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> bool:
        """Check if a table has exactly one matching row."""
        return (
            self.get_row_count(
                object_path=object_path,
                where_conditions=where_conditions,
            )
            == 1
        )

    # DML operations

    @abc.abstractmethod
    def insert_into(
        self,
        table_path: str,
        data: dict[str, Any],
        **kwargs: Any,
    ) -> QueryExecResult:
        """Insert a single row into a table.

        Builds and executes an INSERT INTO statement from the
        provided column-value mapping.

        Args:
            table_path: fully qualified table path (e.g. schema.table).
            data: mapping of column names to values for the new row.

        Returns:
            The result of the INSERT query execution.
        """
        raise NotImplementedMethodException(self.__class__, "insert_into")

    @abc.abstractmethod
    def upsert_into(
        self,
        table_path: str,
        data: dict[str, Any],
        upsert_fields: list[str],
        **kwargs: Any,
    ) -> QueryExecResult:
        """Insert a row or update it on conflict.

        Builds and executes an INSERT ... ON CONFLICT DO UPDATE
        statement. Non-conflict columns are updated with the new
        values when a conflict on the specified fields is detected.

        Args:
            table_path: fully qualified table path (e.g. schema.table).
            data: mapping of column names to values.
            upsert_fields: columns that form the conflict target.

        Returns:
            The result of the UPSERT query execution.
        """
        raise NotImplementedMethodException(self.__class__, "upsert_into")

    @abc.abstractmethod
    def delete_from(
        self,
        table_path: str,
        where_conditions: dict[str, Any],
        **kwargs: Any,
    ) -> QueryExecResult:
        """Delete rows from a table matching the given conditions.

        Builds and executes a DELETE FROM ... WHERE statement.
        Multiple conditions are combined with AND.

        Args:
            table_path: fully qualified table path (e.g. schema.table).
            where_conditions: mapping of column names to values for
                the WHERE clause.

        Returns:
            The result of the DELETE query execution.
        """
        raise NotImplementedMethodException(self.__class__, "delete_from")

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

        Rows are split into batches of ``batch_size`` and each batch
        is executed as a single INSERT statement with inlined literal
        values. Subclasses must override this method.

        Args:
            table_path: fully qualified table path (e.g. schema.table).
            rows: list of row tuples to insert.
            column_list: columns to insert into (from the row tuples).
            conflict_merge_fields: optional conflict target columns
                for ON CONFLICT (used for upsert semantics).
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
        raise NotImplementedMethodException(self.__class__, "bulk_insert_into")

    def insert_into_from_query(
        self,
        table_path: str,
        sql_query: str,
        column_list: list[str],
        **kwargs: Any,
    ) -> QueryExecResult:
        """Insert rows into a table from a SELECT query.

        Builds and executes an INSERT INTO ... SELECT statement
        using the provided column list and query.

        Args:
            table_path: fully qualified table path (e.g. schema.table).
            sql_query: the SELECT query providing the data to insert.
            column_list: columns to insert into.

        Returns:
            The result of the INSERT query execution.
        """
        raise NotImplementedMethodException(self.__class__, "insert_into_from_query")

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

        Builds and executes an INSERT INTO ... SELECT ... ON CONFLICT
        DO UPDATE SET statement. Non-conflict columns are updated when
        a conflict on the specified fields is detected.

        Args:
            table_path: fully qualified table path (e.g. schema.table).
            sql_query: the SELECT query providing the data.
            column_list: columns to insert into.
            upsert_fields: columns that form the conflict target.
            exclude_from_update: columns to omit from the UPDATE SET
                clause entirely (e.g. insert-only timestamp fields).
            expression_overrides: columns to set to a custom SQL
                expression instead of EXCLUDED.col on update.
            exclude_from_match: columns to keep in UPDATE SET but
                exclude from the change-detection clause.

        Returns:
            The result of the UPSERT query execution.
        """
        raise NotImplementedMethodException(self.__class__, "upsert_from_query")

    def delete_from_query(
        self,
        table_path: str,
        sql_query: str,
        key_columns: list[str],
        **kwargs: Any,
    ) -> QueryExecResult:
        """Delete rows from a table whose keys match a SELECT query.

        Builds and executes a DELETE statement that removes rows
        from the target table where the key columns match values
        returned by the provided SELECT query.

        Args:
            table_path: fully qualified table path (e.g. schema.table).
            sql_query: the SELECT query returning key values to delete.
            key_columns: columns used to match rows for deletion.

        Returns:
            The result of the DELETE query execution.
        """
        raise NotImplementedMethodException(self.__class__, "delete_from_query")

    def mark_absent_rows_deleted(
        self,
        table_path: str,
        sql_query: str,
        key_columns: list[str],
        deletion_flag_column: str,
        **kwargs: Any,
    ) -> QueryExecResult:
        """Flag target rows absent from the query as logically deleted.

        Sets the deletion flag to TRUE for every row whose key is not
        returned by ``sql_query``. Rows already flagged are skipped so
        reruns do not rewrite the whole table. The SQL is rendered by
        the connector's DML builder (``build_mark_absent_rows_deleted_query``).

        Args:
            table_path: fully qualified table path (e.g. schema.table).
            sql_query: the SELECT query returning the surviving keys.
            key_columns: columns used to match target rows to the query.
            deletion_flag_column: the boolean flag column to raise.

        Returns:
            The result of the UPDATE query execution.
        """
        table_path = self.clean_object_path(table_path)
        update_query = self.get_dml_builder().build_mark_absent_rows_deleted_query(
            table_path=table_path,
            sql_query=sql_query,
            key_columns=key_columns,
            deletion_flag_column=deletion_flag_column,
        )
        return self.execute_query(
            query=QueryWrapper(
                query=update_query,
                name=table_path,
            ),
        )

    def create_or_replace_view(
        self,
        view_path: str,
        sql_query: str,
    ) -> QueryExecResult:
        """Create or replace a database view from a SELECT query.

        Args:
            view_path: fully qualified view path (e.g. schema.view_name).
            sql_query: the SELECT query defining the view.

        Returns:
            The result of the CREATE OR REPLACE VIEW query execution.
        """
        create_view_query = QueryWrapper(
            query=f"CREATE OR REPLACE VIEW {view_path} AS ({sql_query})",
            name=view_path,
        )
        return self.execute_query(query=create_view_query)

    def execute_transfo(
        self,
        table_path: str,
        operation: DataTransformationOperation,
        data: dict[str, Any] | None = None,
        upsert_fields: list[str] | None = None,
        where_conditions: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> QueryExecResult:
        """Unified entry point for insert, upsert, and delete operations.

        Dispatches to the appropriate DML method based on the
        requested operation type.

        Args:
            table_path: fully qualified table path (e.g. schema.table).
            operation: the DML operation to perform.
            data: column-value mapping (required for insert and upsert).
            upsert_fields: conflict target columns (required for upsert).
            where_conditions: WHERE clause conditions (required for delete).

        Returns:
            The result of the dispatched query execution.
        """
        if operation == DataTransformationOperation.INSERT:
            if data is None:
                raise ValueError("data is required for insert operations")
            return self.insert_into(
                table_path=table_path,
                data=data,
                **kwargs,
            )
        elif operation == DataTransformationOperation.UPSERT:
            if data is None:
                raise ValueError("data is required for upsert operations")
            if upsert_fields is None:
                raise ValueError("upsert_fields is required for upsert operations")
            return self.upsert_into(
                table_path=table_path,
                data=data,
                upsert_fields=upsert_fields,
                **kwargs,
            )
        elif operation == DataTransformationOperation.DELETE:
            if where_conditions is None:
                raise ValueError("where_conditions is required for delete operations")
            return self.delete_from(
                table_path=table_path,
                where_conditions=where_conditions,
                **kwargs,
            )
        else:
            raise ValueError(f"Unsupported operation: {operation}")


class ObjectStorageConnector[CONNECTION_WRAPPER: ConnectionWrapper[Any, Any]](
    DataConnector[CONNECTION_WRAPPER]
):
    def __init__(self, connection_wrapper: CONNECTION_WRAPPER) -> None:
        super().__init__(connection_wrapper)

    def upload_file_from_local_path(
        self, local_file_path: str, obj_storage_path: str, **kwargs: Any
    ) -> None:
        raise NotImplementedMethodException(
            self.__class__, "upload_file_from_local_path"
        )

    def upload_files_from_local_paths(
        self, base_prefix: str, file_paths: Iterable[Path], **kwargs: Any
    ) -> None:
        raise NotImplementedMethodException(
            self.__class__, "upload_file_from_local_path"
        )

    def upload_df_to_csv_file(
        self, df: pd.DataFrame, obj_storage_path: str, **kwargs: Any
    ) -> None:
        raise NotImplementedMethodException(self.__class__, "upload_df_to_csv_file")

    def _get_blobs_list(self, prefix: str | None = None, **kwargs: Any) -> list[str]:
        raise NotImplementedMethodException(self.__class__, "_get_blobs_list")

    def _get_blobs_list_recursive(
        self, prefix: str | None = None, **kwargs: Any
    ) -> list[str]:
        raise NotImplementedMethodException(self.__class__, "_get_blobs_list_recursive")

    def _delete_blob_folder(self, folder_path: str, **kwargs: Any) -> Any:
        raise NotImplementedMethodException(self.__class__, "_delete_blob_folder")

    def _move_blob_folder(
        self,
        src_folder_path: str,
        dst_folder_path: str,
        keep_original: bool = False,
        **kwargs: Any,
    ) -> Any:
        raise NotImplementedMethodException(self.__class__, "_move_blob_folder")
