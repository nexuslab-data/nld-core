from typing import Any

import click

from nld.cli import params, requires_wrapper
from nld.cli.flow import params_flow
from nld.flow.sql import SQLRenderingExecutionTask
from nld.logging import StandardNldFormatter
from nld.structure.task import (
    StructureAdaptTask,
    StructureDeployExecuteTask,
    StructureDeployPlanTask,
    StructureInfoTask,
)
from nld.task.task_utils import execute_task

from . import params_structure


@click.group(name="structure", no_args_is_help=True)
@click.pass_context
def structure(ctx: click.Context, /, **kwargs: Any) -> None:
    """Structure commands"""


@requires_wrapper.nld_command(
    group=structure,
    command_name="adapt",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params_structure.adapter_name
@params_structure.source_structure_name
@params_structure.source_structure_namespace
@params.nld_root_folder_path
@params.output_folder_name_not_required
@params.output_inside_project
def structure_adapt(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Adapt a structure using a structure adapter."""
    return execute_task(StructureAdaptTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command(
    group=structure,
    command_name="info",
    logger_formatter=StandardNldFormatter(),
    silent_completion=True,
    with_project=True,
)
@params_structure.structure_name
@params_structure.structure_namespace
@params.nld_root_folder_path
def structure_info(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Get structure information."""
    return execute_task(StructureInfoTask)  # type: ignore[no-any-return]


@click.group(name="deploy", no_args_is_help=True)
@click.pass_context
def deploy(ctx: click.Context, /, **kwargs: Any) -> None:
    """Deploy commands for structures."""


structure.add_command(deploy)


@requires_wrapper.nld_command(
    group=deploy,
    command_name="plan",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params_structure.structure_name_optional
@params_structure.structure_namespace
@params.nld_root_folder_path
def deploy_plan(ctx: Any, **kwargs: Any) -> Any:
    """Compute a deployment plan and write a manifest."""
    return execute_task(StructureDeployPlanTask)


@requires_wrapper.nld_command(
    group=deploy,
    command_name="execute",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params_structure.structure_name_optional
@params_structure.structure_namespace
@params_structure.from_plan
@params_structure.manifest_path
@params.nld_root_folder_path
def deploy_execute(ctx: Any, **kwargs: Any) -> Any:
    """Execute structure deployment.

    When --from-plan is provided, executes pending manifests.
    Otherwise, computes diffs and deploys inline.
    """
    return execute_task(StructureDeployExecuteTask)


@requires_wrapper.nld_command(
    group=structure,
    command_name="render",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params_flow.flow_name
@params_flow.flow_namespace
@params.nld_root_folder_path
def structure_render(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Render a SQL SELECT query from a flow definition."""
    return execute_task(SQLRenderingExecutionTask)  # type: ignore[no-any-return]
