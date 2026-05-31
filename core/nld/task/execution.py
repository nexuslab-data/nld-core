from datetime import datetime, timedelta

import nld.utils.datetime_util as datetime_util
from nld.pydantic import NldBaseModel
from nld.utils import NldStrEnum
from nld.utils.datetime_util import get_current_datetime


class ExecutionStatus(NldStrEnum):
    ONGOING = "ONGOING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ExecutionInfo(NldBaseModel):
    completion_label: str | None = None
    error_message: str | None = None
    exec_name: str
    uuid: str
    started_at: datetime
    success: bool | None = None
    completed_at: datetime | None = None

    def update_execution_status_to_completed(self) -> None:
        self._update_execution_status_at_completion(ExecutionStatus.SUCCEEDED)

    def update_execution_status_to_failed(
        self,
        error_message: str | None = None,
    ) -> None:
        self.error_message = error_message
        self._update_execution_status_at_completion(ExecutionStatus.FAILED)

    def _update_execution_status_at_completion(self, status: str) -> None:
        assert self.completed_at is None, (
            "Execution status cannot be updated if 'completed_at' is already set"
        )
        assert status in [
            ExecutionStatus.FAILED,
            ExecutionStatus.SUCCEEDED,
        ], f"The execution status cannot be set to the provided status : '{status}'."
        self.success = True if status == ExecutionStatus.SUCCEEDED else False
        self.completed_at = get_current_datetime()

    def get_execution_status(self) -> str:
        return ExecutionStatus.SUCCEEDED if self.success else ExecutionStatus.FAILED

    def get_start_message(self) -> str:
        started_at_str = datetime_util.format_timestamp_to_hour_string(self.started_at)
        return (
            f"Execution `{self.exec_name}` started at {started_at_str} "
            f"with uuid {self.uuid}"
        )

    def get_completion_message(self) -> str:
        status = (
            ExecutionStatus.SUCCEEDED.lower()
            if self.success
            else ExecutionStatus.FAILED.lower()
        )
        elapsed = (
            self.completed_at - self.started_at
            if self.completed_at is not None
            else timedelta()
        )
        started_at_str = datetime_util.format_timestamp_to_short_hour_string(
            self.started_at,
        )
        completed_at_str = datetime_util.format_timestamp_to_short_hour_string(
            self.completed_at
            if self.completed_at is not None
            else datetime_util.get_current_datetime(),
        )
        duration = datetime_util.format_to_compact_duration(elapsed)
        label = self.completion_label or f"Execution `{self.exec_name}`"
        message = (
            f"{label} {status} \n"
            f"Duration: {duration} ({started_at_str} → {completed_at_str})"
        )
        if not self.success and self.error_message:
            message += f"\nError: {self.error_message}"
        return message
