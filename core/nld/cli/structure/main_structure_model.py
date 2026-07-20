from typing import Any

import click

from nld.cli import params, requires_wrapper
from nld.logging import StandardNldFormatter
from nld.structure.task import (
    StructureModelInfoTask,
    StructureModelListTask,
    StructureModelValidateTask,
)
from nld.task.task_utils import execute_task

from . import params_structure


@click.group(name="model", no_args_is_help=True)
@click.pass_context
def model(ctx: click.Context, /, **kwargs: Any) -> None:
    """Structure model commands (inter-structure links and field mappings)."""


@requires_wrapper.nld_command(
    group=model,
    command_name="list",
    logger_formatter=StandardNldFormatter(),
    silent_completion=True,
    with_project=True,
)
@params_structure.structure_namespace
@params.nld_root_folder_path
def model_list(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """List the structure models visible from a namespace."""
    return execute_task(StructureModelListTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command(
    group=model,
    command_name="info",
    logger_formatter=StandardNldFormatter(),
    silent_completion=True,
    with_project=True,
)
@params_structure.structure_model_name
@params_structure.structure_namespace
@params_structure.structure_model_info_output
@params.nld_root_folder_path
def model_info(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Show a structure model's links and field mappings."""
    return execute_task(StructureModelInfoTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command(
    group=model,
    command_name="validate",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params_structure.structure_model_name_optional
@params_structure.structure_namespace
@params.nld_root_folder_path
def model_validate(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Validate structure model field mappings against referenced structures."""
    return execute_task(StructureModelValidateTask)  # type: ignore[no-any-return]
