from functools import update_wrapper
from typing import Any

from nld.cli.cli_events import CommandCompleted, CommandRuntimeError
from nld.cli.cli_exceptions import ExceptionExit
from nld.flow.execution import FlowExecutionInfo, FlowExecutionInfoWrapper
from nld.logging import InfoEvent, WarnEvent, log_event_default
from nld.task.context import NldExecutionContext

_EMPTY_CELL = "-"
_NUMERIC_COLUMNS = ("Duration", "Inserted", "Updated", "Deleted")


class FlowSummaryCompleted(InfoEvent):
    """Info event for logging the flow execution summary."""

    def __init__(self, summary: str):
        super().__init__()
        self._summary = summary

    def code(self) -> str:
        return "FLW-001"

    def message(self) -> str:
        return self._summary


class BatchFlowSummaryCompleted(InfoEvent):
    """Info event for logging the batch flow execution summary."""

    def __init__(self, summary: str):
        super().__init__()
        self._summary = summary

    def code(self) -> str:
        return "FLW-002"

    def message(self) -> str:
        return self._summary


class BatchFlowSummaryWarning(WarnEvent):
    """Warning event when batch execution has failures."""

    def __init__(self, summary: str):
        super().__init__()
        self._summary = summary

    def code(self) -> str:
        return "FLW-003"

    def message(self) -> str:
        return self._summary


def _build_execution_summary(batch_info: FlowExecutionInfoWrapper) -> str:
    """Build a formatted summary table for batch execution results."""
    lines: list[str] = []
    if batch_info.namespace and batch_info.namespace != ".":
        lines.append(f"Execution summary for namespace '{batch_info.namespace}':")
    else:
        lines.append("Execution summary:")
    lines.append("")

    flow_info_by_id = {
        _display_id_from_flow_result(result): result
        for result in batch_info.flow_results
    }

    rows: list[dict[str, str]] = []
    for flow_id in batch_info.execution_order:
        status_label, status_detail = _status_for_flow(
            batch_info=batch_info,
            flow_id=flow_id,
        )
        result = flow_info_by_id.get(flow_id)
        rows.append(
            {
                "Flow": flow_id,
                "Status": status_label
                + (f" ({status_detail})" if status_detail else ""),
                "Duration": _format_duration_cell(result=result),
                "Inserted": _format_count_cell(
                    result=result,
                    attr="target_entries_inserted_in_success",
                ),
                "Updated": _format_count_cell(
                    result=result,
                    attr="target_entries_updated_in_success",
                ),
                "Deleted": _format_deleted_cell(result=result),
            },
        )

    column_names = ["Flow", "Status", "Duration", "Inserted", "Updated", "Deleted"]
    widths = {
        column: max(
            len(column),
            *(len(row[column]) for row in rows),
        )
        for column in column_names
    }

    header_cells = [_pad_cell(column, width=widths[column]) for column in column_names]
    lines.append("  " + "  ".join(header_cells))
    lines.append("  " + "  ".join("─" * widths[column] for column in column_names))

    for row in rows:
        cells = [
            _pad_cell(row[column], width=widths[column], column=column)
            for column in column_names
        ]
        lines.append("  " + "  ".join(cells))

    lines.append("")
    succeeded_count = len(batch_info.succeeded_flows)
    failed_count = len(batch_info.failed_flows)
    skipped_count = len(batch_info.skipped_flows)
    skipped_views_count = len(batch_info.skipped_views)
    summary_parts = [
        f"Total: {batch_info.total_flows}",
        f"Succeeded: {succeeded_count}",
    ]
    if failed_count > 0:
        summary_parts.append(f"Failed: {failed_count}")
    if skipped_count > 0:
        summary_parts.append(f"Skipped: {skipped_count}")
    if skipped_views_count > 0:
        summary_parts.append(f"Views skipped: {skipped_views_count}")
    lines.append(f"  {' | '.join(summary_parts)}")

    return "\n".join(lines)


def _pad_cell(value: str, width: int, column: str | None = None) -> str:
    """Left-pad numeric columns, left-align textual ones."""
    if column in _NUMERIC_COLUMNS:
        return value.rjust(width)
    return value.ljust(width)


def _status_for_flow(
    batch_info: FlowExecutionInfoWrapper,
    flow_id: str,
) -> tuple[str, str | None]:
    if flow_id in batch_info.succeeded_flows:
        return "SUCCEEDED", None
    if flow_id in batch_info.failed_flows:
        return "FAILED", batch_info.failed_flows[flow_id]
    if flow_id in batch_info.skipped_flows:
        predecessor = batch_info.skipped_flows[flow_id]
        return "SKIPPED", f"predecessor '{predecessor}' failed"
    if flow_id in batch_info.skipped_views:
        return "SKIPPED", "view"
    return "UNKNOWN", None


def _format_duration_cell(result: FlowExecutionInfo | None) -> str:
    duration = _compute_flow_duration_seconds(result=result)
    if duration is None:
        return _EMPTY_CELL
    return f"{duration:.1f}s"


def _format_count_cell(result: FlowExecutionInfo | None, attr: str) -> str:
    total = _sum_step_counts(result=result, attrs=(attr,))
    if total is None:
        return _EMPTY_CELL
    return f"{total:,}"


def _format_deleted_cell(result: FlowExecutionInfo | None) -> str:
    """Sum hard deletes and logical deletes for a combined cell."""
    total = _sum_step_counts(
        result=result,
        attrs=(
            "target_entries_deleted_in_success",
            "target_entries_logically_deleted_in_success",
        ),
    )
    if total is None:
        return _EMPTY_CELL
    return f"{total:,}"


def _sum_step_counts(
    result: FlowExecutionInfo | None,
    attrs: tuple[str, ...],
) -> int | None:
    """Sum the given numeric step fields across `result.steps`.

    Returns `None` when `result` or `result.steps` is missing; returns
    0 when there are steps but none report the requested field.
    """
    if result is None or not result.steps:
        return None
    total: int | None = None
    for step in result.steps:
        for attr in attrs:
            value = getattr(step, attr, None)
            if value is None:
                continue
            total = (total or 0) + value
    return total


def _compute_flow_duration_seconds(
    result: FlowExecutionInfo | None,
) -> float | None:
    if result is None or result.started_at is None or result.ended_at is None:
        return None
    return (result.ended_at - result.started_at).total_seconds()


def _display_id_from_flow_result(result: FlowExecutionInfo) -> str:
    if result.flow_namespace and result.flow_namespace != ".":
        return f"{result.flow_namespace}.{result.flow_name}"
    return result.flow_name


def _handle_execution_result(batch_info: FlowExecutionInfoWrapper) -> None:
    """Log the batch summary and raise ExceptionExit if any flow failed.

    The summary table is suppressed for single-flow runs since the
    per-flow log already contains everything it would show.
    """
    should_render_summary = batch_info.total_flows > 1

    if batch_info.failed_flows:
        if should_render_summary:
            summary = _build_execution_summary(batch_info=batch_info)
            log_event_default(BatchFlowSummaryWarning(summary=summary))
        raise ExceptionExit(
            RuntimeError(
                f"Batch execution failed: {len(batch_info.failed_flows)} flow(s) failed"
            )
        )

    if should_render_summary:
        summary = _build_execution_summary(batch_info=batch_info)
        log_event_default(BatchFlowSummaryCompleted(summary=summary))


def manage_flow_cli_exception(
    func: Any = None,
    silent_completion: bool = False,
) -> Any:
    """Handles exception handling for flow CLI commands.

    Extends the base exception handling pattern with flow-specific
    summary logging when the command returns a FlowExecutionInfo
    or a FlowExecutionInfoWrapper.

    Args:
        func: The function to wrap
        silent_completion: When True, skip logging the CommandCompleted event
    """

    def decorator(f: Any) -> Any:
        def wrapper(*args, **kwargs):  # type: ignore
            caught_exception: Exception | None = None
            exception_occurred = False
            try:
                success = f(*args, **kwargs)
                if isinstance(success, FlowExecutionInfoWrapper):
                    _handle_execution_result(batch_info=success)
            except ExceptionExit:
                exception_occurred = True
                raise
            except (RuntimeError, Exception) as ex:
                exception_occurred = True
                caught_exception = ex
                log_event_default(CommandRuntimeError(e=ex))
                raise ExceptionExit(ex) from ex
            finally:
                execution_context = NldExecutionContext.get_current()
                if execution_context is not None:
                    exec_info = execution_context.exec_info
                    if exception_occurred:
                        error_msg = (
                            str(caught_exception)
                            if caught_exception
                            else "batch execution failed"
                        )
                        exec_info.update_execution_status_to_failed(
                            error_message=error_msg,
                        )
                    else:
                        exec_info.update_execution_status_to_completed()
                    if not silent_completion:
                        log_event_default(
                            CommandCompleted(exec_info=exec_info),
                        )
            return success

        return update_wrapper(wrapper, f)

    if func is not None:
        return decorator(func)
    return decorator
