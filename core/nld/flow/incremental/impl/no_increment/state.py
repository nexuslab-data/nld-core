import datetime

from nld.flow.incremental.models import (
    FlowPlannedProcessingDetailledState,
    FlowPlannedProcessingState,
    FlowProcessingState,
    FlowSourceState,
    FlowState,
    IncrementalProcessingStatus,
)
from nld.utils.datetime_util import get_current_datetime
from nld.utils.user_display import (
    format_datetime_for_display,
    format_key_value_lines,
)


class NoIncrementState(FlowState):
    def render_state_text(self) -> str:
        """Render the empty state; no_increment tracks no authoritative state."""
        return "  (empty)"


class NoIncrementSourceState(FlowSourceState):
    pass


class NoIncrementProcessingState(FlowProcessingState):
    processing_completed_at: datetime.datetime | None = None
    processing_status: str = IncrementalProcessingStatus.TO_BE_PROCESSED
    process_error_message: str | None = None

    def set_to_succeeded(self) -> None:
        self.processing_status = IncrementalProcessingStatus.SUCCEEDED
        self.process_error_message = None
        self.processing_completed_at = get_current_datetime()

    def set_to_failed(self, error_message: str | None = None) -> None:
        self.processing_status = IncrementalProcessingStatus.FAILED
        self.process_error_message = error_message
        self.processing_completed_at = get_current_datetime()

    def get_display_log(self) -> str:
        """Return a human-readable summary of the processing state."""
        return f"Strategy: {self.strategy} (no increment)"

    def render_state_text(self) -> str:
        """Render the run outcome for the single no_increment unit of work."""
        pairs: list[tuple[str, str]] = [("Status", str(self.processing_status))]
        if self.processing_completed_at is not None:
            pairs.append(
                (
                    "Completed at",
                    format_datetime_for_display(value=self.processing_completed_at),
                )
            )
        if self.process_error_message is not None:
            pairs.append(("Error", str(self.process_error_message)))
        return "\n".join(format_key_value_lines(pairs=pairs))


class NoIncrementPlannedProcessingDetailledState(
    FlowPlannedProcessingDetailledState[NoIncrementProcessingState],
):
    """Plan-time detail for a no_increment PLANNED plan."""

    strategy: str

    def to_processing_state(self, flow_uid: str) -> NoIncrementProcessingState:
        return NoIncrementProcessingState(
            flow_uid=flow_uid,
            strategy=self.strategy,
        )

    @classmethod
    def from_processing_state(
        cls,
        plan_state_uid: str,
        processing_state: NoIncrementProcessingState,
    ) -> "NoIncrementPlannedProcessingDetailledState":
        return cls(
            plan_state_uid=plan_state_uid,
            strategy=processing_state.strategy,
        )


class NoIncrementPlannedProcessingState(
    FlowPlannedProcessingState[NoIncrementPlannedProcessingDetailledState],
):
    """A PLANNED plan carrying a no_increment planned-detail payload."""
