from typing import Any

import click

from nld.cli import params, requires_wrapper
from nld.cli.flow.requires_flow import manage_flow_cli_exception
from nld.flow.task import (
    DataFlowDependencyGraphTask,
    DataFlowExecutionTask,
    DataFlowInfoTask,
    FlowStateIncrementalComputeTask,
)
from nld.flow.task.data_flow_deploy_execute_task import FlowDeployExecuteTask
from nld.flow.task.data_flow_deploy_plan_task import FlowDeployPlanTask
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
@params_flow.deps_downstream
@params_flow.deps_upstream
@params_flow.full
@params_flow.render
@params_flow.with_delta
@params_flow.with_views
@params_flow.state_compute_only
@params_flow.planned_state_strategy
def flow_execute(
    ctx: click.Context,
    **kwargs: Any,
) -> Any:
    """Execute a data flow by name, or all flows in a namespace.

    With --state-compute-only, the flow is not executed; instead the
    incremental processing state is computed and persisted, exactly like
    'nld flow state incremental compute --persist'.
    """
    from nld.task.context import NldExecutionContext

    nld_execution_context = NldExecutionContext.require_current()
    task_params = nld_execution_context.task_request.get_parameters()

    name = task_params.get("name")
    namespace = task_params.get("namespace")

    if name is None and namespace is None:
        raise click.UsageError("Either --name or --namespace must be provided.")

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


@click.group(name="deploy", no_args_is_help=True)
@click.pass_context
def deploy(ctx: click.Context, /, **kwargs: Any) -> None:
    """Deploy commands for flows."""


flow.add_command(deploy)


@requires_wrapper.nld_command(
    group=deploy,
    command_name="plan",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params.nld_root_folder_path
@params_flow.flow_name_optional
@params_flow.flow_namespace
@params_flow.deploy_downstream
@params_flow.deploy_upstream
@params_flow.interactive
@params_flow.no_backfill
def deploy_plan(ctx: Any, **kwargs: Any) -> Any:
    """Compute a deployment plan and write a manifest."""
    return execute_task(FlowDeployPlanTask)


@requires_wrapper.nld_command(
    group=deploy,
    command_name="execute",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params.nld_root_folder_path
@params_flow.manifest_path
@params_flow.no_backfill
@params_flow.with_backfill
@params_flow.plan_only
@params_flow.from_plan
@params_flow.deploy_execute_interactive
def deploy_execute(ctx: Any, **kwargs: Any) -> Any:
    """Plan and apply a deployment in one shot, or apply manifest(s).

    By default, builds a deployment plan in memory from the current entity
    state, prompts the user to confirm (unless --no-interactive), and
    executes it. Backfill is **suppressed by default** in this mode to
    avoid rewriting historical data on a one-shot deploy — pass
    --with-backfill to opt in. Pass --plan-only to write the plan as a
    manifest YAML and exit without executing — equivalent to
    `nld flow deploy plan`.

    Pass --from-plan to opt into the manifest-based mode: when
    --manifest-path is provided, executes that single manifest;
    otherwise, auto-discovers and executes all pending manifests in
    .deployments/flows/. --manifest-path implies --from-plan. In this
    mode the backfill strategy is governed by the manifest entries;
    pass --no-backfill to override and skip backfill globally.

    --plan-only is mutually exclusive with --from-plan.
    --with-backfill is mutually exclusive with --from-plan and
    --no-backfill.
    """
    return execute_task(FlowDeployExecuteTask)
