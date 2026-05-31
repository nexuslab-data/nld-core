from typing import Any

import click

from nld.cli import params, requires_wrapper
from nld.flow.sql import SQLRenderingExecutionTask
from nld.logging import StandardNldFormatter
from nld.task.task_utils import execute_task

from . import params_sql


@click.group(name="sql", no_args_is_help=True)
@click.pass_context
def sql(ctx: click.Context, /, **kwargs: Any) -> None:
    """SQL commands"""


@requires_wrapper.nld_command(
    group=sql,
    command_name="render",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params_sql.flow_name
@params_sql.flow_namespace
@params_sql.in_project
@params.nld_root_folder_path
def sql_render(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Render SQL SELECT queries from flow definitions.

    When neither --name nor --namespace is provided, renders all SQL
    flows in the project.
    """
    return execute_task(SQLRenderingExecutionTask)  # type: ignore[no-any-return]
