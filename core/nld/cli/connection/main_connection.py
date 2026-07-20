from typing import Any

import click

from nld.cli import params, requires_wrapper
from nld.cli.connection import params_connection
from nld.connector.task import (
    ConnectionDebugTask,
    ConnectionExportEnvironmentVariablesTask,
    ConnectionExportQueryCsvTask,
    ConnectionGetStructureTask,
    ConnectionListTask,
)
from nld.task.task_utils import execute_task


@requires_wrapper.nld_command("debug")
@params.specific_connection_params
def debug(ctx: click.Context, **kwargs: Any) -> bool:
    """Test the connection availability and status"""
    return execute_task(ConnectionDebugTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command("export-env-var")
@params.specific_connection_params
def export_env_var(ctx: click.Context, **kwargs: Any) -> bool:
    """
    Export environment variables for a connection to the parent terminal.

    To load variables into your current shell, use eval:

        eval "$(nld connection export-env-var --connection-name <name>)"

    With a specific profile:

        eval "$(nld connection export-env-var \
        --connection-name <name> --profile-name <profile>)"
    """
    return execute_task(ConnectionExportEnvironmentVariablesTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command("get-structure")
@params.specific_connection_params
@params_connection.database
@params.namespace
@params_connection.schema
@params_connection.object_name
def get_structure(ctx: click.Context, **kwargs: Any) -> bool:
    """Extract database structure from a connection.

    Extracts metadata about tables, views, columns, primary keys, and
    unique constraints. Output is in YAML format.

    Examples:

        nld connection get-structure --connection-name my_conn

        nld connection get-structure --connection-name my_conn --schema public

        nld connection get-structure --connection-name my_conn --namespace source.raw

        nld connection get-structure --connection-name my_conn --object users
    """
    return execute_task(ConnectionGetStructureTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command("export-query-csv")
@params.specific_connection_params
@params_connection.query
@params_connection.query_file
@params_connection.output_file
@params_connection.delimiter
@params_connection.no_header
def export_query_csv(ctx: click.Context, **kwargs: Any) -> bool:
    """Export the result of a SELECT query to a CSV file.

    Only read-only SELECT (or WITH) queries are accepted. The query can
    be passed inline or read from a .sql file.

    Examples:

        nld connection export-query-csv --connection-name my_conn \
            --query "SELECT * FROM users" --output-file users.csv

        nld connection export-query-csv --connection-name my_conn \
            --query-file users.sql --delimiter ";"
    """
    return execute_task(ConnectionExportQueryCsvTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command("list")
def list_connections(ctx: click.Context, **kwargs: Any) -> bool:
    """List all available connections"""
    return execute_task(ConnectionListTask)  # type: ignore[no-any-return]
