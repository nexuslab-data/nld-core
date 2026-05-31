from typing import Any

import click

from nld.cli import params, requires_wrapper
from nld.cli.project import params_project
from nld.logging import StandardNldFormatter
from nld.project.task import ProjectEntityInfoTask, ProjectInfoTask
from nld.task.task_utils import execute_task


@requires_wrapper.nld_command(
    "info",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params.nld_root_folder_path
@params_project.namespace
def info(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Get the project general information"""
    return execute_task(ProjectInfoTask)  # type: ignore[no-any-return]


@click.group(name="entity", no_args_is_help=True)
@click.pass_context
def entity(ctx: click.Context, /, **kwargs: Any) -> None:
    """Entity management commands"""


@requires_wrapper.nld_command(
    group=entity,
    command_name="info",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params.nld_root_folder_path
@params_project.namespace
@params_project.entity_type
def entity_info(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Get an entity general information"""
    return execute_task(ProjectEntityInfoTask)  # type: ignore[no-any-return]
