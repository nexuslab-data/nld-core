from typing import Any

import click

from nld.cli import params, requires_wrapper
from nld.logging import StandardNldFormatter
from nld.structure.task import (
    StructureAuditInfoTask,
    StructureAuditListTask,
    StructureAuditRenderTask,
    StructureAuditRunTask,
    StructureAuditValidateTask,
)
from nld.task.task_utils import execute_task

from . import params_structure


@click.group(name="audit", no_args_is_help=True)
@click.pass_context
def audit(ctx: click.Context, /, **kwargs: Any) -> None:
    """Structure audit commands (standardised data analysis audits)."""


@requires_wrapper.nld_command(
    group=audit,
    command_name="list",
    logger_formatter=StandardNldFormatter(),
    silent_completion=True,
    with_project=True,
)
@params_structure.structure_namespace
@params.nld_root_folder_path
def audit_list(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """List the structure audits visible from a namespace."""
    return execute_task(StructureAuditListTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command(
    group=audit,
    command_name="info",
    logger_formatter=StandardNldFormatter(),
    silent_completion=True,
    with_project=True,
)
@params_structure.structure_audit_name
@params_structure.structure_namespace
@params.nld_root_folder_path
def audit_info(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Show a structure audit's target, metadata, columns and distributions."""
    return execute_task(StructureAuditInfoTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command(
    group=audit,
    command_name="run",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params_structure.structure_audit_name
@params_structure.structure_namespace
@params_structure.structure_audit_run_connection
@params.profile_name
@params_structure.structure_audit_run_sample
@params_structure.structure_audit_run_environment
@params_structure.structure_audit_run_force
@params_structure.structure_audit_run_new_version
@params.nld_root_folder_path
def audit_run(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Profile a structure's physical table and write a StructureAudit YAML.

    Measures the live table (row count, per-column coverage and distinct counts,
    min/max, low-cardinality distributions) and writes the audit under
    `assets/audits/structure/<namespace>/`. Skips an existing audit unless
    `--force` is passed, or use `--new-version` to write a timestamped audit
    alongside the canonical one.
    """
    return execute_task(StructureAuditRunTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command(
    group=audit,
    command_name="validate",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params_structure.structure_audit_name_optional
@params_structure.structure_namespace
@params.nld_root_folder_path
def audit_validate(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Validate structure audit columns against the referenced structure."""
    return execute_task(StructureAuditValidateTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command(
    group=audit,
    command_name="render",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params_structure.structure_audit_name
@params_structure.structure_namespace
@params_structure.structure_audit_render_override_output_folder_path
@params_structure.structure_audit_render_stdout
@params.nld_root_folder_path
def audit_render(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Render a structure audit to a standard markdown report.

    By default writes to a timestamped folder under `output/`; use
    `--override-output-folder-path` to choose the folder or `--stdout` to print.
    """
    return execute_task(StructureAuditRenderTask)  # type: ignore[no-any-return]
