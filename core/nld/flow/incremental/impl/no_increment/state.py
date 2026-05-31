import datetime

from nld.flow.incremental.models import (
    FlowPlannedProcessingState,
    FlowProcessingState,
    FlowSourceState,
    FlowState,
    IncrementalProcessingStatus,
)
from nld.utils.datetime_util import get_current_datetime


class NoIncrementState(FlowState):
    pass


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


class NoIncrementPlannedProcessingState(
    FlowPlannedProcessingState[NoIncrementProcessingState],
):
    """A PLANNED plan carrying a no_increment processing-state payload."""
