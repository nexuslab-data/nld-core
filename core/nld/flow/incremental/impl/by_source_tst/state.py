import datetime

from pydantic import field_validator

from nld.flow.incremental.models import (
    FlowPlannedProcessingDetailedState,
    FlowPlannedProcessingState,
    FlowProcessingState,
    FlowSourceState,
    FlowState,
    IncrementalProcessingStatus,
)
from nld.utils.datetime_util import ensure_utc_datetime, get_current_datetime
from nld.utils.user_display import (
    format_datetime_for_display,
    format_datetime_range,
    format_key_value_lines,
)


class BySourceTstState(FlowState):
    last_pull_to_timestamp: datetime.datetime | None = None

    @field_validator(
        "last_pull_to_timestamp",
        mode="before",
    )
    @classmethod
    def validate_utc_timezone(
        cls,
        value: datetime.datetime | None,
    ) -> datetime.datetime | None:
        """Enforce UTC timezone on all timestamp fields."""
        return ensure_utc_datetime(value)

    def render_state_text(self) -> str:
        """Render the authoritative watermark the next run resumes from."""
        pairs: list[tuple[str, str]] = []
        if self.last_pull_to_timestamp is not None:
            pairs.append(
                (
                    "Last pull to",
                    format_datetime_for_display(value=self.last_pull_to_timestamp),
                )
            )
        lines = format_key_value_lines(pairs=pairs)
        if not lines:
            lines.append("  (empty)")
        return "\n".join(lines)


class BySourceTstSourceState(FlowSourceState):
    pass


class BySourceTstProcessingState(FlowProcessingState):
    pull_from_timestamp: datetime.datetime | None = None
    pull_to_timestamp: datetime.datetime | None = None
    processing_status: str = IncrementalProcessingStatus.TO_BE_PROCESSED
    process_error_message: str | None = None
    processing_completed_at: datetime.datetime | None = None

    @field_validator(
        "pull_from_timestamp",
        "pull_to_timestamp",
        "processing_completed_at",
        mode="before",
    )
    @classmethod
    def validate_utc_timezone(
        cls,
        value: datetime.datetime | None,
    ) -> datetime.datetime | None:
        """Enforce UTC timezone on all timestamp fields."""
        return ensure_utc_datetime(value)

    def set_to_be_processed(self) -> None:
        self.processing_status = IncrementalProcessingStatus.TO_BE_PROCESSED

    def set_to_succeeded(self) -> None:
        self.processing_status = IncrementalProcessingStatus.SUCCEEDED
        self.process_error_message = None
        self.processing_completed_at = get_current_datetime()

    def set_to_failed(self, error_message: str | None = None) -> None:
        self.processing_status = IncrementalProcessingStatus.FAILED
        self.process_error_message = error_message
        self.processing_completed_at = get_current_datetime()

    def get_pull_timestamps(
        self,
    ) -> tuple[datetime.datetime | None, datetime.datetime | None]:
        """Return the source timestamp pull range."""
        return self.pull_from_timestamp, self.pull_to_timestamp

    def get_display_log(self) -> str:
        """Return a human-readable summary of the processing state."""
        if self.pull_from_timestamp is not None and self.pull_to_timestamp is not None:
            range_display = f"[{self.pull_from_timestamp} → {self.pull_to_timestamp}]"
        elif self.pull_from_timestamp is None and self.pull_to_timestamp is not None:
            range_display = f"[→ {self.pull_to_timestamp}]"
        else:
            range_display = "no range"
        return f"Strategy: {self.strategy} | Range: {range_display}"

    def render_state_text(self) -> str:
        """Render the pull window and outcome of the most recent run."""
        pairs: list[tuple[str, str]] = []
        pull_range = format_datetime_range(
            start=self.pull_from_timestamp,
            end=self.pull_to_timestamp,
        )
        if pull_range is not None:
            pairs.append(("Pull", pull_range))
        pairs.append(("Status", str(self.processing_status)))
        if self.processing_completed_at is not None:
            pairs.append(
                (
                    "Completed at",
                    format_datetime_for_display(value=self.processing_completed_at),
                )
            )
        if self.process_error_message is not None:
            pairs.append(("Error", str(self.process_error_message)))
        lines = format_key_value_lines(pairs=pairs)
        if not lines:
            lines.append("  (empty)")
        return "\n".join(lines)

    def to_be_processed(self) -> bool:
        return self.processing_status == IncrementalProcessingStatus.TO_BE_PROCESSED

    def succeeded(self) -> bool:
        return self.processing_status == IncrementalProcessingStatus.SUCCEEDED

    def failed(self) -> bool:
        return self.processing_status == IncrementalProcessingStatus.FAILED


class BySourceTstPlannedProcessingDetailedState(
    FlowPlannedProcessingDetailedState[BySourceTstProcessingState],
):
    """Plan-time detail for a by_source_tst PLANNED plan."""

    strategy: str
    pull_from_timestamp: datetime.datetime | None = None
    pull_to_timestamp: datetime.datetime | None = None

    @field_validator(
        "pull_from_timestamp",
        "pull_to_timestamp",
        mode="before",
    )
    @classmethod
    def validate_utc_timezone(
        cls,
        value: datetime.datetime | None,
    ) -> datetime.datetime | None:
        """Enforce UTC timezone on all timestamp fields."""
        return ensure_utc_datetime(value)

    def to_processing_state(self, flow_uid: str) -> BySourceTstProcessingState:
        return BySourceTstProcessingState(
            flow_uid=flow_uid,
            strategy=self.strategy,
            pull_from_timestamp=self.pull_from_timestamp,
            pull_to_timestamp=self.pull_to_timestamp,
        )

    @classmethod
    def from_processing_state(
        cls,
        plan_state_uid: str,
        processing_state: BySourceTstProcessingState,
    ) -> "BySourceTstPlannedProcessingDetailedState":
        return cls(
            plan_state_uid=plan_state_uid,
            strategy=processing_state.strategy,
            pull_from_timestamp=processing_state.pull_from_timestamp,
            pull_to_timestamp=processing_state.pull_to_timestamp,
        )


class BySourceTstPlannedProcessingState(
    FlowPlannedProcessingState[BySourceTstPlannedProcessingDetailedState],
):
    """A PLANNED plan carrying a by_source_tst planned-detail payload."""
