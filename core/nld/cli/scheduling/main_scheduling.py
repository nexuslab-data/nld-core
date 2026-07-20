from typing import Any

import click

from nld.cli import params, requires_wrapper
from nld.logging import StandardNldFormatter
from nld.scheduling.task import (
    SchedulingDependencyGraphTask,
    SchedulingValidateTask,
)
from nld.task.task_utils import execute_task

from . import params_scheduling


@click.group(name="scheduling", no_args_is_help=True)
@click.pass_context
def scheduling(ctx: click.Context, /, **kwargs: Any) -> None:
    """Scheduling commands (environment-aware flow scheduling)."""


@requires_wrapper.nld_command(
    group=scheduling,
    command_name="validate",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params.nld_root_folder_path
@params_scheduling.environment
def scheduling_validate(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Validate an environment's scheduling has no cycles."""
    return execute_task(SchedulingValidateTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command(
    group=scheduling,
    command_name="deps",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params.nld_root_folder_path
@params_scheduling.environment
@params_scheduling.output_format
@params_scheduling.deps_flow_name
@params_scheduling.deps_namespace
@params_scheduling.deps_downstream
@params_scheduling.deps_upstream
def scheduling_deps(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Output the scheduling dependency graph for an environment."""
    return execute_task(SchedulingDependencyGraphTask)  # type: ignore[no-any-return]
