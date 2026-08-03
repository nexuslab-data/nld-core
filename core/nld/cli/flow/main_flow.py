from typing import Any

import click

from nld.cli import params, requires_wrapper
from nld.cli.flow.requires_flow import manage_flow_cli_exception
from nld.flow.deploy.flow_change_set import FlowChangeSet
from nld.flow.task import (
    DataFlowDependencyGraphTask,
    DataFlowExecutionTask,
    DataFlowInfoTask,
    FlowStateIncrementalComputeTask,
)
from nld.flow.task.data_flow_deploy_task import FlowDeployTask
from nld.logging import StandardNldFormatter
from nld.task.task_utils import execute_task

from . import params_flow
from .state_flow import state as state_group


@click.group(name="flow", no_args_is_help=True)
@click.pass_context
def flow(ctx: click.Context, /, **kwargs: Any) -> None:
    """Flow commands"""


flow.add_command(state_group)


@requires_wrapper.nld_command(
    group=flow,
    command_name="info",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params_flow.flow_name
@params_flow.flow_namespace
@params.nld_root_folder_path
def flow_info(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Get data flow information."""
    return execute_task(DataFlowInfoTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command(
    group=flow,
    command_name="deps",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params.nld_root_folder_path
@params_flow.output_format
@params_flow.deps_flow_name
@params_flow.deps_structure_name
@params_flow.deps_namespace
@params_flow.deps_downstream
@params_flow.deps_upstream
@params_flow.deps_override_output_folder_path
def flow_deps(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Output the flow dependency graph."""
    return execute_task(DataFlowDependencyGraphTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command(
    group=flow,
    command_name="execute",
    completion_label="Flow execution",
    logger_formatter=StandardNldFormatter(),
    ignore_unknown_options=True,
    allow_extra_args=True,
    with_project=True,
    manage_cli_exception=manage_flow_cli_exception,
)
@params.nld_root_folder_path
@params_flow.flow_name_optional
@params_flow.flow_namespace
@params.profile_name
@params_flow.deps_downstream
@params_flow.deps_upstream
@params_flow.full
@params_flow.render
@params_flow.with_delta
@params_flow.with_views
@params_flow.state_compute_only
@params_flow.planned_state_policy
def flow_execute(
    ctx: click.Context,
    **kwargs: Any,
) -> Any:
    """Execute a data flow by name, or all flows in a namespace.

    When neither --name nor --namespace is given, every flow in the
    project is executed in dependency order.

    With --state-compute-only, the flow is not executed; instead the
    incremental processing state is computed and persisted, exactly like
    'nld flow state incremental compute --persist'.

    --profile-name selects a single credential profile applied to every
    connection the flow opens, including the state backend. It overrides
    any per-connection profile pinned in the flow definition; when it is
    omitted, each connection falls back to its definition profile and then
    to its default profile.
    """
    from nld.task.context import NldExecutionContext

    nld_execution_context = NldExecutionContext.require_current()
    task_params = nld_execution_context.task_request.get_parameters()

    name = task_params.get("name")

    if task_params.get("state_compute_only"):
        # State compute is a single-flow operation backed by the same
        # task as 'nld flow state incremental compute', so lineage
        # fan-out has no meaning here.
        if name is None:
            raise click.UsageError("--state-compute-only requires --name.")
        if task_params.get("downstream") or task_params.get("upstream"):
            raise click.UsageError(
                "--state-compute-only is incompatible with --downstream / --upstream.",
            )
        return execute_task(
            FlowStateIncrementalComputeTask,
            extra_init_params={
                "persist": True,
                # State compute never mutates target data, so the source
                # request is always auto-confirmed without prompting.
                "confirm_source_request": lambda message: True,
            },
        )

    return execute_task(DataFlowExecutionTask)


@requires_wrapper.nld_command(
    group=flow,
    command_name="deploy",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params.nld_root_folder_path
@params_flow.flow_name_optional
@params_flow.flow_namespace
@params_flow.deploy_downstream
@params_flow.deploy_upstream
@params_flow.deploy_interactive
@params_flow.deploy_preview
@params_flow.deploy_output
@params_flow.deploy_adopt
@params_flow.deploy_allow_drift
@params_flow.deploy_rebuild
def flow_deploy(ctx: Any, **kwargs: Any) -> Any:
    """Deploy the committed flow & structure definitions to the target.

    The change set is always computed in memory against the live
    target and applied immediately: deployment changes shape and
    records state, it never executes flows. Pass --preview to print
    the computed change set (including the structure DDL) without
    applying anything — the command then exits with code 2 when
    changes are pending (0 when in sync) and --output writes the
    change set as JSON. --no-interactive skips the confirmation
    prompt, for CI pipelines.

    A target modified outside nld refuses the deploy by default;
    --adopt records the live schema as a flagged baseline first,
    --allow-drift deploys against it anyway, and --rebuild
    recreates the in-scope structures from the assets.
    """
    result = execute_task(FlowDeployTask)
    if (
        kwargs.get("preview")
        and isinstance(result, FlowChangeSet)
        and not result.is_empty()
    ):
        # Distinct exit code so CI drift gates can branch on
        # "changes pending" without parsing output.
        ctx.exit(2)
    return result
