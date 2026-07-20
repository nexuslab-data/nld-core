import datetime
from collections import defaultdict
from decimal import Decimal
from typing import Any

from pydantic import ConfigDict, Field

from nld.flow.utils import FlowExecStatus, FlowStepCategory, FlowStepExecStatus
from nld.pydantic import NldBaseModel
from nld.utils.datetime_util import get_current_datetime


class FlowStepExecutionInfo(NldBaseModel):
    flow_uid: str
    step_name: str
    step_category: str | None = None
    started_at: datetime.datetime
    ended_at: datetime.datetime | None = None
    duration_seconds: Decimal | None = None
    query: str | None = None
    step_status: str | None = None
    step_error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    custom_kpis: dict[str, Any] = Field(default_factory=dict)
    source_entries_in_success: int | None = None
    source_entries_in_error: int | None = None
    target_entries_inserted_in_success: int | None = None
    target_entries_inserted_in_error: int | None = None
    target_entries_updated_in_success: int | None = None
    target_entries_updated_in_error: int | None = None
    target_entries_logically_deleted_in_success: int | None = None
    target_entries_logically_deleted_in_error: int | None = None
    target_entries_deleted_in_success: int | None = None
    target_entries_deleted_in_error: int | None = None
    files_moved_in_success: int | None = None
    files_moved_in_error: int | None = None
    files_deleted_in_success: int | None = None
    files_deleted_in_error: int | None = None

    def get_entries_summary(self) -> str | None:
        """Compact summary of source/target row counts for display.

        Surfaces the per-step entry metrics (rows read from the source,
        rows inserted/updated/deleted in the target) that are otherwise
        only available in the JSON output. Only non-null metrics are
        included; a non-zero error count is appended as ``!<n>`` so a
        partially failed step stands out. Returns None when the step
        carries no row-count information (e.g. a pre-processing step).
        """
        labelled = [
            ("src", self.source_entries_in_success, self.source_entries_in_error),
            (
                "ins",
                self.target_entries_inserted_in_success,
                self.target_entries_inserted_in_error,
            ),
            (
                "upd",
                self.target_entries_updated_in_success,
                self.target_entries_updated_in_error,
            ),
            (
                "ldel",
                self.target_entries_logically_deleted_in_success,
                self.target_entries_logically_deleted_in_error,
            ),
            (
                "del",
                self.target_entries_deleted_in_success,
                self.target_entries_deleted_in_error,
            ),
        ]
        parts = [
            segment
            for label, success, error in labelled
            if (segment := self._format_count_segment(label, success, error))
        ]
        return " ".join(parts) if parts else None

    def get_files_summary(self) -> str | None:
        """Compact summary of file-movement counts for display.

        Mirrors ``get_entries_summary`` for the file metrics (files moved
        into / deleted from the landing zone). Returns None when the step
        carries no file information.
        """
        labelled = [
            ("moved", self.files_moved_in_success, self.files_moved_in_error),
            ("del", self.files_deleted_in_success, self.files_deleted_in_error),
        ]
        parts = [
            segment
            for label, success, error in labelled
            if (segment := self._format_count_segment(label, success, error))
        ]
        return " ".join(parts) if parts else None

    @staticmethod
    def _format_count_segment(
        label: str, success: int | None, error: int | None
    ) -> str | None:
        """Format one ``label:<success>[!<error>]`` count segment.

        Returns None when both counts are absent so the segment is dropped
        from the summary entirely rather than rendered as a zero.
        """
        if success is None and error is None:
            return None
        segment = f"{label}:{success or 0}"
        if error:
            segment += f"!{error}"
        return segment

    def update_execution_status_to_completed(self, with_warning: bool = False) -> None:
        self._update_execution_status_at_completion(
            FlowStepExecStatus.SUCCEEDED
            if not with_warning
            else FlowStepExecStatus.SUCCEEDED_WITH_WARNING
        )

    def update_execution_status_to_failed(self, error_message: str) -> None:
        self._update_execution_status_at_completion(FlowStepExecStatus.FAILED)
        self.step_error = error_message

    def _update_execution_status_at_completion(self, status: str) -> None:
        assert self.ended_at is None, (
            "Execution status cannot be updated if 'ended_at' is already set"
        )
        assert status in [
            FlowStepExecStatus.FAILED,
            FlowStepExecStatus.SUCCEEDED,
            FlowStepExecStatus.SUCCEEDED_WITH_WARNING,
        ], f"The execution status cannot be set to the provided status : '{status}'."
        self.step_status = status
        self.ended_at = get_current_datetime()
        duration = (self.ended_at - self.started_at).total_seconds()
        self.duration_seconds = Decimal(str(duration)).quantize(Decimal("0.1"))


class FlowExecutionInfo(NldBaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "functional_key": {
                "fields": ["flow_namespace", "flow_name"],
                "name": "fk_flow_execution_info",
            }
        }
    )

    flow_uid: str = Field(json_schema_extra={"primary_key": True})
    flow_namespace: str
    flow_name: str
    flow_instance_name: str
    requestor: str
    data_load_strategy: str
    started_at: datetime.datetime | None = None
    ended_at: datetime.datetime | None = None
    execution_status: str | None = None
    execution_error: str | None = None
    pull_from: datetime.datetime | None = None
    pull_to: datetime.datetime | None = None
    previous_layer_last_updated_at: datetime.datetime | None = None
    source_extracted_at: datetime.datetime | None = None
    source_last_updated_at: datetime.datetime | None = None
    steps: list[FlowStepExecutionInfo] | None = None

    def update_execution_status_to_completed(self, with_warning: bool = False) -> None:
        self._update_execution_status_at_completion(
            FlowExecStatus.SUCCEEDED
            if not with_warning
            else FlowExecStatus.SUCCEEDED_WITH_WARNING
        )

    def update_execution_status_to_failed(
        self,
        error_message: str | None = None,
    ) -> None:
        self._update_execution_status_at_completion(FlowExecStatus.FAILED)
        self.execution_error = error_message

    def _update_execution_status_at_completion(self, status: str) -> None:
        assert self.ended_at is None, (
            "Execution status cannot be updated if 'ended_at' is already set"
        )
        assert status in [
            FlowExecStatus.FAILED,
            FlowExecStatus.SUCCEEDED,
            FlowExecStatus.SUCCEEDED_WITH_WARNING,
        ], f"The execution status cannot be set to the provided status : '{status}'."
        self.execution_status = status
        self.ended_at = get_current_datetime()

    def get_summary_message(self) -> str | None:
        """Build a summary string from step row counts and incremental fields.

        Returns None if neither row count data nor incremental
        timestamps are available.
        """
        parts: list[str] = []

        row_summary = self.get_row_count_summary()
        if row_summary:
            parts.append(row_summary)

        incremental_summary = self._get_incremental_summary()
        if incremental_summary:
            parts.append(incremental_summary)

        if not parts:
            return None
        return "\n".join(parts)

    def get_row_count_summary(self) -> str | None:
        """Aggregate row counts by operation type across FLOW_EXECUTION steps."""
        if not self.steps:
            return None

        counts_by_operation: dict[str, int] = defaultdict(int)
        for step in self.steps:
            if step.step_category == FlowStepCategory.FLOW_EXECUTION:
                row_count = step.metadata.get("row_count")
                operation_type = step.metadata.get("operation_type")
                if row_count is not None and operation_type is not None:
                    counts_by_operation[operation_type.lower()] += row_count

        if not counts_by_operation:
            return None

        segments = [
            f"{count:,} {operation}{'d' if operation.endswith('e') else 'ed'}".replace(
                ",", " "
            )
            for operation, count in counts_by_operation.items()
        ]
        return f"Rows: {' | '.join(segments)}"

    def _get_incremental_summary(self) -> str | None:
        """Format incremental timestamp ranges if available."""
        lines: list[str] = []

        if self.pull_from is not None or self.pull_to is not None:
            pull_from_str = self._format_incremental_timestamp(self.pull_from)
            pull_to_str = self._format_incremental_timestamp(self.pull_to)
            lines.append(f"Pull: {pull_from_str} → {pull_to_str}")

        technical_lines = self._get_technical_timestamp_lines()
        if technical_lines:
            lines.extend(technical_lines)

        if not lines:
            return None
        return "\n".join(lines)

    def _get_technical_timestamp_lines(self) -> list[str]:
        """Format technical metadata timestamps if available."""
        lines: list[str] = []
        if self.previous_layer_last_updated_at is not None:
            lines.append(
                "Previous layer last updated at: "
                f"{self._format_incremental_timestamp(self.previous_layer_last_updated_at)}"
            )
        if self.source_extracted_at is not None:
            lines.append(
                "Source extracted at: "
                f"{self._format_incremental_timestamp(self.source_extracted_at)}"
            )
        if self.source_last_updated_at is not None:
            lines.append(
                "Source last updated at: "
                f"{self._format_incremental_timestamp(self.source_last_updated_at)}"
            )
        return lines

    @staticmethod
    def _format_incremental_timestamp(
        ts: datetime.datetime | None,
    ) -> str:
        """Format an incremental timestamp to a readable date-time string."""
        if ts is None:
            return "N/A"
        return ts.strftime("%Y-%m-%d %H:%M")


class FlowExecutionHistory(NldBaseModel):
    executions: list[FlowExecutionInfo]


class FlowExecutionState(NldBaseModel):
    last_processed: FlowExecutionInfo | None = None
