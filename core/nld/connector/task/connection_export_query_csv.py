from __future__ import annotations

from typing import Any

from nld.connector.base import (
    NonSelectQueryException,
    QueryExecutionException,
    SQLDataConnector,
)
from nld.parameters import ExecutionParameterDefinition
from nld.task import StandardTask
from nld.task.context import NldExecutionContext

DEFAULT_OUTPUT_FILE_NAME = "query_result.csv"
DEFAULT_DELIMITER = ","


class ConnectionExportQueryCsvTask(StandardTask):
    """Task to export the result of a SELECT query to a CSV file.

    This task runs a read-only SELECT query against a configured
    connection and writes the result set to a CSV file. Only SELECT
    (or WITH) statements are accepted so the database cannot be mutated.

    Example:
        >>> task = ConnectionExportQueryCsvTask()
        >>> task.run(
        ...     connection_name="my_connection",
        ...     query="SELECT * FROM users",
        ...     output_file="users.csv",
        ... )
    """

    init_params = []
    run_params = [
        ExecutionParameterDefinition(name="connection_name", mandatory=True),
        ExecutionParameterDefinition(name="query", mandatory=False),
        ExecutionParameterDefinition(name="query_file", mandatory=False),
        ExecutionParameterDefinition(name="output_file", mandatory=False),
        ExecutionParameterDefinition(name="delimiter", mandatory=False),
        ExecutionParameterDefinition(name="no_header", mandatory=False),
    ]

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the task."""
        super().__init__(**kwargs)
        self.execution_context = NldExecutionContext.require_current()

    def run(  # type: ignore[override]
        self,
        connection_name: str,
        query: str | None = None,
        query_file: str | None = None,
        output_file: str | None = None,
        delimiter: str | None = None,
        no_header: bool = False,
        **kwargs: Any,
    ) -> bool:
        """Execute the query and export its result to a CSV file.

        Args:
            connection_name: Name of the connection to query.
            query: Inline SELECT query to execute.
            query_file: Path to a .sql file holding the SELECT query.
                Used when ``query`` is not provided.
            output_file: Destination CSV file path. Defaults to
                ``query_result.csv`` in the current folder.
            delimiter: CSV field delimiter. Defaults to a comma.
            no_header: When True, omit the header row from the CSV file.
            **kwargs: Additional keyword arguments.

        Returns:
            True if the export was successful, False otherwise.
        """
        query_text = self._resolve_query_text(
            query=query,
            query_file=query_file,
        )
        if query_text is None:
            self.log_error(
                "A query must be provided through --query or --query-file",
            )
            return False

        output_file_path = output_file or DEFAULT_OUTPUT_FILE_NAME
        field_delimiter = delimiter or DEFAULT_DELIMITER

        connector = self.execution_context.get_data_connector(
            connection_name,
            open_connection=True,
        )
        if not isinstance(connector, SQLDataConnector):
            self.log_error(
                f"Connection '{connection_name}' is not a SQL connector and "
                f"cannot export query results to CSV",
            )
            return False

        try:
            row_count = connector.export_query_to_csv(
                query=query_text,
                output_file_path=output_file_path,
                delimiter=field_delimiter,
                include_header=not no_header,
            )
        except NonSelectQueryException as exc:
            self.log_error(exc.message)
            return False
        except QueryExecutionException as exc:
            self.log_error(f"Query execution failed: {exc.message}")
            return False

        self.log_info(
            f"Exported {row_count} row(s) to {output_file_path}",
        )
        return True

    def _resolve_query_text(
        self,
        query: str | None,
        query_file: str | None,
    ) -> str | None:
        """Return the query text from the inline value or the SQL file."""
        if query:
            return query
        if query_file:
            with open(query_file, encoding="utf-8") as sql_file:
                return sql_file.read()
        return None
