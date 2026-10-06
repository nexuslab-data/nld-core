from typing import Any

import click

from nld.cli import params, requires_wrapper
from nld.cli.flow import params_flow
from nld.flow.sql import SQLRenderingExecutionTask
from nld.flow.structure_generation import StructureGenerateTask
from nld.logging import StandardNldFormatter
from nld.structure.task import (
    StructureAdaptTask,
    StructureInfoTask,
    StructureListTask,
    StructureValidateTask,
)
from nld.task.task_utils import execute_task

from . import params_structure
from .main_structure_audit import audit
from .main_structure_deploy import deploy
from .main_structure_model import model


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


@requires_wrapper.nld_command(
    group=structure,
    command_name="list",
    logger_formatter=StandardNldFormatter(),
    silent_completion=True,
    with_project=True,
)
@params_structure.structure_namespace
@params_structure.property_filter
@params_structure.tag_filter
@params.nld_root_folder_path
def structure_list(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """List structures, optionally filtered by --property key=value and --tag."""
    return execute_task(StructureListTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command(
    group=structure,
    command_name="validate",
    logger_formatter=StandardNldFormatter(),
    silent_completion=True,
    with_project=True,
)
@params_structure.structure_name_optional
@params_structure.structure_namespace
@params_structure.display_format
@params.nld_root_folder_path
def structure_validate(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Validate field characterisation pertinence for structures.

    Validates one structure when --name is given, otherwise every structure
    visible from --namespace. Each field characterisation is checked against the
    known catalogue (built-in defaults merged with project definitions).
    """
    return execute_task(StructureValidateTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command(
    group=structure,
    command_name="generate",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params_flow.flow_name_optional
@params_flow.flow_namespace
@params_structure.generate_check
@params.nld_root_folder_path
def structure_generate(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Generate a flow target structure from the flow's single predecessor.

    With --name, generates the target structure of that flow, creating its
    YAML file when missing and merging into it otherwise. Without --name,
    regenerates every already generated structure whose flow is visible from
    --namespace. With --check, writes nothing and exits non-zero when a
    generated structure is stale.
    """
    return execute_task(StructureGenerateTask)  # type: ignore[no-any-return]


structure.add_command(deploy)
structure.add_command(model)
structure.add_command(audit)


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
