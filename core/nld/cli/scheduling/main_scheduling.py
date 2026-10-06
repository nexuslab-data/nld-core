from typing import Any

import click

from nld.cli import params, requires_wrapper
from nld.logging import StandardNldFormatter
from nld.scheduling.task import (
    SchedulingDependencyGraphTask,
    SchedulingFrequencyTask,
    SchedulingInfoTask,
    SchedulingListTask,
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
@params_scheduling.deps_task_name
@params_scheduling.deps_namespace
@params_scheduling.deps_downstream
@params_scheduling.deps_upstream
@params_scheduling.deps_override_output_folder_path
def scheduling_deps(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Output the scheduling dependency graph for an environment."""
    return execute_task(SchedulingDependencyGraphTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command(
    group=scheduling,
    command_name="frequency",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params.nld_root_folder_path
@params_scheduling.environment
@params_scheduling.frequency_filter
def scheduling_frequency(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Report the intended execution frequency of an environment's flows."""
    return execute_task(SchedulingFrequencyTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command(
    group=scheduling,
    command_name="info",
    logger_formatter=StandardNldFormatter(),
    silent_completion=True,
    with_project=True,
)
@params_scheduling.task_name
@params_scheduling.task_namespace
@params.nld_root_folder_path
def scheduling_info(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Get scheduled flow task information."""
    return execute_task(SchedulingInfoTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command(
    group=scheduling,
    command_name="list",
    logger_formatter=StandardNldFormatter(),
    silent_completion=True,
    with_project=True,
)
@params_scheduling.task_namespace
@params_scheduling.environment
@params.nld_root_folder_path
def scheduling_list(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """List scheduled flow tasks, optionally scoped to one environment."""
    return execute_task(SchedulingListTask)  # type: ignore[no-any-return]
