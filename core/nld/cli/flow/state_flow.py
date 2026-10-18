"""Click subcommand group ``nld flow state``.

Commands that emit persisted flow state. Only ``compute --persist`` and
``exclude-keys`` write to the state backend. The default stdout
rendering is a concise human-friendly summary; ``--format json`` emits
the full machine-readable payload. ``--output`` always writes JSON to a
file. Reads always go to the primary state backend.

Layout::

    nld flow state execution get-state    <name> [--namespace]
                                                 [--format text|json] [--output]
    nld flow state execution get-history  <name> [--namespace] [--limit]
                                                 [--format text|json] [--output]
    nld flow state execution get-steps    <name> [--namespace]
                                                 (--flow-uid UID | --latest)
                                                 [--format text|json] [--output]
    nld flow state incremental get-state  <name> [--namespace]
                                                 [--processing-only]
                                                 [--format text|json] [--output]
    nld flow state incremental get-planned <name> [--namespace]
                                                 [--format text|json] [--output]
    nld flow state incremental compute    <name> [--namespace]
                                                 [--persist] [--requestor U]
                                                 [--source-request-authorized]
                                                 [--format text|json] [--output]
    nld flow state incremental exclude-keys <name> --keys K1,K2 [--namespace]
                                                 [--format text|json] [--output]
"""

from typing import Any

import click

from nld.cli import params, requires_wrapper
from nld.flow.task import (
    FlowStateExecutionGetHistoryTask,
    FlowStateExecutionGetStateTask,
    FlowStateExecutionGetStepsTask,
    FlowStateIncrementalComputeTask,
    FlowStateIncrementalExcludeKeysTask,
    FlowStateIncrementalGetPlannedTask,
    FlowStateIncrementalGetStateTask,
)
from nld.logging import StandardNldFormatter
from nld.task.task_utils import execute_task

from . import params_flow


@click.group(name="state", no_args_is_help=True)
@click.pass_context
def state(ctx: click.Context, /, **kwargs: Any) -> None:
    """Inspect persisted flow state (execution and incremental).

    The get-* subcommands accept --profile-name to select the credential
    profile of the state backend connection they read from.
    """


@state.group(name="execution", no_args_is_help=True)
@click.pass_context
def state_execution(ctx: click.Context, /, **kwargs: Any) -> None:
    """Read-only access to a flow's execution history."""


@state.group(name="incremental", no_args_is_help=True)
@click.pass_context
def state_incremental(ctx: click.Context, /, **kwargs: Any) -> None:
    """Access to a flow's incremental state.

    The get-* subcommands only read it; compute --persist saves a plan and
    exclude-keys updates the key state of a by_key flow.
    """


@requires_wrapper.nld_command(
    group=state_execution,
    command_name="get-state",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params.nld_root_folder_path
@params_flow.flow_name
@params_flow.flow_namespace
@params.profile_name
@params_flow.state_file_output_params
def flow_state_execution_get_state(ctx: click.Context, **kwargs: Any) -> Any:
    """Return the latest persisted execution info (text by default)."""
    return execute_task(FlowStateExecutionGetStateTask)


@requires_wrapper.nld_command(
    group=state_execution,
    command_name="get-history",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params.nld_root_folder_path
@params_flow.flow_name
@params_flow.flow_namespace
@params.profile_name
@params_flow.state_history_limit
@params_flow.state_file_output_params
def flow_state_execution_get_history(ctx: click.Context, **kwargs: Any) -> Any:
    """Return the persisted execution history (text by default)."""
    return execute_task(FlowStateExecutionGetHistoryTask)


@requires_wrapper.nld_command(
    group=state_execution,
    command_name="get-steps",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params.nld_root_folder_path
@params_flow.flow_name
@params_flow.flow_namespace
@params.profile_name
@params_flow.state_steps_flow_uid
@params_flow.state_steps_latest
@params_flow.state_file_output_params
def flow_state_execution_get_steps(ctx: click.Context, **kwargs: Any) -> Any:
    """Return the step list of a single execution (text by default)."""
    return execute_task(FlowStateExecutionGetStepsTask)


@requires_wrapper.nld_command(
    group=state_incremental,
    command_name="get-state",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params.nld_root_folder_path
@params_flow.flow_name
@params_flow.flow_namespace
@params.profile_name
@params_flow.state_processing_only
@params_flow.state_file_output_params
def flow_state_incremental_get_state(ctx: click.Context, **kwargs: Any) -> Any:
    """Return the current incremental state (text by default)."""
    return execute_task(FlowStateIncrementalGetStateTask)


@requires_wrapper.nld_command(
    group=state_incremental,
    command_name="get-planned",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params.nld_root_folder_path
@params_flow.flow_name
@params_flow.flow_namespace
@params.profile_name
@params_flow.state_file_output_params
def flow_state_incremental_get_planned(ctx: click.Context, **kwargs: Any) -> Any:
    """List the PLANNED plans for the flow (text by default)."""
    return execute_task(FlowStateIncrementalGetPlannedTask)


@requires_wrapper.nld_command(
    group=state_incremental,
    command_name="compute",
    logger_formatter=StandardNldFormatter(),
    ignore_unknown_options=True,
    allow_extra_args=True,
    with_project=True,
)
@params.nld_root_folder_path
@params_flow.flow_name
@params_flow.flow_namespace
@params.profile_name
@params_flow.state_compute_persist
@params_flow.state_compute_requestor
@params_flow.state_compute_source_request_authorized
@params_flow.state_file_output_params
def flow_state_incremental_compute(ctx: click.Context, **kwargs: Any) -> Any:
    """Compute the next processing state without executing the flow.

    Drives ``compute_incremental_state`` on the flow's DataFlowTask
    without writing the live processing-state slot or any execution-
    history row. With ``--persist``, the result is saved to the state
    backend as a PLANNED plan, cancelling any prior PLANNED plan.

    Extra incremental kwargs (e.g. ``--limit``) are passed through to the
    underlying DataFlowTask exactly like ``nld flow execute``, so the
    computed plan reflects the parameters the next execution would use.
    """
    return execute_task(
        FlowStateIncrementalComputeTask,
        extra_init_params={
            "confirm_source_request": (
                lambda message: click.confirm(message, default=False)
            ),
        },
    )


@requires_wrapper.nld_command(
    group=state_incremental,
    command_name="exclude-keys",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params.nld_root_folder_path
@params_flow.flow_name
@params_flow.flow_namespace
@params.profile_name
@params_flow.state_exclude_keys
@params_flow.state_file_output_params
def flow_state_incremental_exclude_keys(ctx: click.Context, **kwargs: Any) -> Any:
    """Set keys of a by_key flow to PERMANENTLY_EXCLUDED.

    DELTA and BACKFILL_DELTA runs never select an excluded key again. Use it
    for a key the flow code cannot classify, e.g. a source answer it cannot
    tell permanent. A key absent from the key state is added. Run it while
    the flow is not running: a run already started may overwrite the change.

    A BACKFILL of the keys (--keys without --with-delta) or a FULL run
    re-attempts them, which undoes the exclusion.
    """
    return execute_task(FlowStateIncrementalExcludeKeysTask)
