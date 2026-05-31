"""Concise human-friendly renderers for ``nld flow state`` commands.

These helpers turn the persisted execution and incremental state models
into compact, operator-oriented text. They are used by
`AbstractDataFlowStateTask._persist_or_print` when the user opts into
the default ``--format text`` rendering. Identifiers already supplied
on the CLI (``flow_namespace``, ``flow_name``) and fields that are a
given of the chosen subcommand (e.g. the incremental ``strategy``,
which is fixed by the flow definition) are intentionally omitted so
the output stays focused on the pertinent values.

Generic display building blocks (tables, datetime/duration formatting,
truncation) live in `nld.utils.user_display` so the same look-and-feel
is reused by `nld project info`, `nld flow info`, `nld structure info`
and any future info/state command.
"""

from typing import Any

from nld.flow.execution import FlowExecutionHistory, FlowExecutionInfo
from nld.flow.execution.execution_info import FlowStepExecutionInfo
from nld.flow.incremental.models import (
    FlowProcessingState,
    FlowState,
    FlowStatePlan,
    IncrementalProcessingStatus,
)
from nld.utils.user_display import (
    format_aligned_table,
    format_datetime_for_display,
    format_datetime_range,
    format_datetime_string_for_display,
    format_datetime_string_range,
    format_duration_between,
    format_key_value_lines,
    format_seconds_compact,
    truncate,
)


def render_execution_state_text(info: FlowExecutionInfo | None) -> str:
    """Render the latest execution as a multi-line text block.

    The execution status, data-load strategy and execution error are
    intentionally omitted: the status is a given for a successful read,
    the strategy is fixed by the flow definition (already visible in
    `nld flow info`), and an execution error cannot reach this view
    because only succeeded executions are persisted as the latest
    state.
    """
    if info is None:
        return "No execution recorded yet.\n"

    duration = format_duration_between(start=info.started_at, end=info.ended_at)
    ended_display = format_datetime_for_display(info.ended_at)
    if duration is not None:
        ended_display = f"{ended_display} ({duration})"

    pairs: list[tuple[str, str]] = [
        ("Started", format_datetime_for_display(info.started_at)),
        ("Ended", ended_display),
    ]
    pull_line = format_datetime_range(start=info.pull_from, end=info.pull_to)
    if pull_line is not None:
        pairs.append(("Pull", pull_line))
    if info.previous_layer_last_updated_at is not None:
        pairs.append(
            (
                "Previous layer updated at",
                format_datetime_for_display(info.previous_layer_last_updated_at),
            )
        )
    if info.source_extracted_at is not None:
        pairs.append(
            (
                "Source extracted at",
                format_datetime_for_display(info.source_extracted_at),
            )
        )
    if info.source_last_updated_at is not None:
        pairs.append(
            (
                "Source last updated at",
                format_datetime_for_display(info.source_last_updated_at),
            )
        )

    row_summary = info.get_row_count_summary()
    if row_summary is not None:
        # Drop the leading "Rows: " segment so the label aligns with the
        # other rows under the shared label column.
        pairs.append(("Rows", row_summary.removeprefix("Rows: ")))

    lines: list[str] = [f"Last Execution: {info.flow_uid}"]
    lines.extend(format_key_value_lines(pairs=pairs))
    return "\n".join(lines) + "\n"


def render_execution_history_text(history: FlowExecutionHistory) -> str:
    """Render the execution history as a fixed-width table.

    The table is wrapped in blank lines so it stands out from any
    preceding initialisation logs printed before the CLI emits the
    rendering.
    """
    if not history.executions:
        return "No executions recorded yet.\n"

    headers = [
        "flow_uid",
        "status",
        "started_at",
        "completed_at",
        "duration",
        "strategy",
    ]
    rows: list[list[str]] = []
    for execution in history.executions:
        rows.append(
            [
                execution.flow_uid,
                execution.execution_status or "N/A",
                format_datetime_for_display(execution.started_at),
                format_datetime_for_display(execution.ended_at),
                format_duration_between(
                    start=execution.started_at,
                    end=execution.ended_at,
                )
                or "N/A",
                execution.data_load_strategy,
            ]
        )
    table_lines = format_aligned_table(headers=headers, rows=rows)
    return "\n" + "\n".join(table_lines) + "\n\n"


def render_execution_steps_text(steps: list[FlowStepExecutionInfo]) -> str:
    """Render the steps of a single execution as a fixed-width table."""
    if not steps:
        return "No steps recorded for this execution.\n"

    headers = ["step_name", "status", "started_at", "duration", "error"]
    rows: list[list[str]] = []
    for step in steps:
        duration = (
            format_seconds_compact(value=step.duration_seconds)
            if step.duration_seconds is not None
            else format_duration_between(start=step.started_at, end=step.ended_at)
        )
        rows.append(
            [
                step.step_name,
                step.step_status or "N/A",
                format_datetime_for_display(step.started_at),
                duration or "N/A",
                truncate(text=step.step_error or "", max_length=60),
            ]
        )
    table_lines = format_aligned_table(headers=headers, rows=rows)
    return "\n" + "\n".join(table_lines) + "\n\n"


def render_incremental_state_text(
    processing: FlowProcessingState | None,
    post_processing: FlowState | None,
    include_post_processing: bool,
) -> str:
    """Render the incremental processing state (optionally with post-state)."""
    if processing is None and (not include_post_processing or post_processing is None):
        return "No incremental state recorded yet.\n"

    sections: list[str] = []

    if processing is not None:
        sections.append("Processing state:\n" + _render_processing_state(processing))
    elif include_post_processing:
        sections.append("Processing state:\n  (not recorded yet)")

    if include_post_processing:
        if post_processing is not None:
            sections.append(
                "Post-processing state:\n"
                + _render_post_processing_state(post_processing)
            )
        else:
            sections.append("Post-processing state:\n  (not recorded yet)")

    return "\n\n".join(sections) + "\n"


def render_stateless_incremental_text(strategy: str) -> str:
    """Render the 'not applicable' notice for stateless strategies.

    Strategies that declare ``tracks_state=False`` (e.g. ``no_increment``,
    used by VIEW flows) never record incremental processing state or
    plans. The read commands report that plainly so they exit cleanly
    instead of surfacing the backend's ``NotImplementedError``.
    """
    return (
        f"Incremental state is not applicable for this flow: strategy "
        f"'{strategy}' does not track incremental state.\n"
    )


def render_plans_not_supported_text(strategy: str) -> str:
    """Render the 'not applicable' notice for plan-disabled strategies.

    A strategy may track incremental state yet declare
    ``supports_planned_state=False``, in which case it never persists a
    PLANNED plan. The plan commands report that plainly so they exit
    cleanly instead of implying that no plan happens to exist yet.
    """
    return (
        f"Planned states are not supported for this flow: strategy "
        f"'{strategy}' does not support planned states.\n"
    )


def _render_processing_state(processing: FlowProcessingState) -> str:
    """Render a single FlowProcessingState as aligned key-value lines."""
    data = processing.model_dump(mode="json", exclude_none=True)
    # The CLI invocation already pins the flow, so flow_uid / strategy
    # are redundant given context — drop them from the text view.
    data.pop("flow_uid", None)
    data.pop("strategy", None)

    pairs: list[tuple[str, str]] = []

    pull_from = data.pop("pull_from_timestamp", None)
    pull_to = data.pop("pull_to_timestamp", None)
    pull_range = format_datetime_string_range(start=pull_from, end=pull_to)
    if pull_range is not None:
        pairs.append(("Pull", pull_range))

    keys = data.pop("keys", None)

    if "processing_status" in data:
        pairs.append(("Status", str(data.pop("processing_status"))))
    if "processing_completed_at" in data:
        pairs.append(
            (
                "Completed at",
                format_datetime_string_for_display(data.pop("processing_completed_at")),
            )
        )
    if "process_error_message" in data:
        pairs.append(("Error", str(data.pop("process_error_message"))))

    for key, value in data.items():
        pairs.append((key, str(value)))

    lines = format_key_value_lines(pairs=pairs)

    if keys is not None and isinstance(keys, dict):
        lines.extend(_render_keys_breakdown(keys=keys))

    if not lines:
        lines.append("  (empty)")
    return "\n".join(lines)


def _render_post_processing_state(post_processing: FlowState) -> str:
    """Render a FlowState (post-processing/authoritative view)."""
    data = post_processing.model_dump(mode="json", exclude_none=True)

    pairs: list[tuple[str, str]] = []

    last_pull_to = data.pop("last_pull_to_timestamp", None)
    if last_pull_to is not None:
        pairs.append(("Last pull to", format_datetime_string_for_display(last_pull_to)))

    keys = data.pop("keys", None)

    for key, value in data.items():
        pairs.append((key, str(value)))

    lines = format_key_value_lines(pairs=pairs)

    if keys is not None and isinstance(keys, dict):
        lines.extend(_render_keys_breakdown(keys=keys, status_field="status"))

    if not lines:
        lines.append("  (empty)")
    return "\n".join(lines)


KEYS_SAMPLE_SIZE = 10


def _render_keys_breakdown(
    keys: dict[str, Any],
    status_field: str = "processing_status",
) -> list[str]:
    """Render aggregate counts of by-key state entries.

    Appends a sample of up to ``KEYS_SAMPLE_SIZE`` TO_BE_PROCESSED key
    names so the operator can spot-check which entries the next run will
    actually process without dumping every key in larger flows.
    """
    counts: dict[str, int] = {}
    to_be_processed: list[str] = []
    for key_name, key_state in keys.items():
        status = (
            key_state.get(status_field) if isinstance(key_state, dict) else None
        ) or "N/A"
        counts[status] = counts.get(status, 0) + 1
        if status == IncrementalProcessingStatus.TO_BE_PROCESSED:
            to_be_processed.append(key_name)

    pairs: list[tuple[str, str]] = [("Keys total", str(len(keys)))]
    for status, count in sorted(counts.items()):
        pairs.append((status, str(count)))
    lines = format_key_value_lines(pairs=pairs)

    sample = to_be_processed[:KEYS_SAMPLE_SIZE]
    if sample:
        header = (
            f"  Sample of to be processed ({len(sample)} of {len(to_be_processed)}):"
            if len(to_be_processed) > len(sample)
            else f"  Sample of to be processed ({len(sample)}):"
        )
        lines.append(header)
        lines.extend(f"    - {name}" for name in sample)
    return lines


def render_planned_processing_state_text(
    processing: FlowProcessingState | None,
    persisted: bool,
    plan_state_uid: str | None = None,
    requestor: str | None = None,
) -> str:
    """Render the result of ``nld flow state incremental compute``.

    Reuses ``_render_processing_state`` for the body, then prepends a
    short metadata header reflecting whether the plan was persisted
    and (when persisted) the plan uid and requestor.
    """
    if processing is None:
        if persisted:
            return "Nothing to compute (no processing state for this strategy).\n"
        return "Nothing to compute (no processing state for this strategy).\n"

    header_pairs: list[tuple[str, str]] = []
    header_pairs.append(("Persisted", "yes" if persisted else "no"))
    if persisted and plan_state_uid is not None:
        header_pairs.append(("Plan uid", plan_state_uid))
    if requestor is not None:
        header_pairs.append(("Requestor", requestor))

    sections: list[str] = []
    if header_pairs:
        header_lines = "\n".join(format_key_value_lines(pairs=header_pairs))
        sections.append("Plan:\n" + header_lines)
    sections.append("Processing state:\n" + _render_processing_state(processing))

    return "\n\n".join(sections) + "\n"


def render_planned_processing_states_text(
    plans: list[FlowStatePlan],
) -> str:
    """Render the PLANNED plans of a flow as a fixed-width table.

    The plan ``status`` (always PLANNED in this listing) and ``strategy``
    (fixed by the flow definition) are omitted so the table focuses on
    the values that vary between plans.
    """
    if not plans:
        return "No planned plans recorded yet.\n"

    headers = [
        "plan_state_uid",
        "computed_at",
        "requestor",
    ]
    rows: list[list[str]] = []
    for plan in plans:
        rows.append(
            [
                plan.plan_state_uid,
                format_datetime_for_display(plan.computed_at),
                plan.requestor or "N/A",
            ]
        )
    table_lines = format_aligned_table(headers=headers, rows=rows)
    return "\n" + "\n".join(table_lines) + "\n\n"
