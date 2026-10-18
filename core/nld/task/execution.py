import re
from datetime import datetime, timedelta
from typing import Any

import nld.utils.datetime_util as datetime_util
from nld.pydantic import NldBaseModel
from nld.utils import NldStrEnum
from nld.utils.datetime_util import get_current_datetime
from nld.utils.user_display import format_key_value_lines

MASKED_PARAMETER_VALUE = "***"
SENSITIVE_PARAMETER_NAME_PATTERN = re.compile(
    r"password|secret|token|credential|private_key",
    flags=re.IGNORECASE,
)


def _format_parameter_lines(parameters: dict[str, Any]) -> list[str]:
    """Render the parameters an execution received, one aligned line each.

    Unset options (``None`` or an empty multi-value option) are left out so
    the block only shows what the run was given. Values whose name looks
    like a secret are masked, as these lines end up in scheduler logs.

    Example: ``{"name": "orders", "full": False, "namespace": None}``
    renders ``["  full: False", "  name: orders"]``.
    """
    pairs: list[tuple[str, str]] = []
    for name, value in sorted(parameters.items()):
        if value is None or (isinstance(value, list | tuple) and not value):
            continue
        if SENSITIVE_PARAMETER_NAME_PATTERN.search(name):
            display_value = MASKED_PARAMETER_VALUE
        elif isinstance(value, list | tuple):
            display_value = ", ".join(str(item) for item in value)
        else:
            display_value = str(value)
        pairs.append((name, display_value))
    return format_key_value_lines(pairs=pairs)


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

    def get_start_message(
        self,
        parameters: dict[str, Any] | None = None,
    ) -> str:
        """Build the start message, followed by the parameters when given."""
        started_at_str = datetime_util.format_timestamp_to_hour_string(self.started_at)
        message = (
            f"Execution `{self.exec_name}` started at {started_at_str} "
            f"with uuid {self.uuid}"
        )
        parameter_lines = _format_parameter_lines(parameters=parameters or {})
        if parameter_lines:
            message += "\nParameters:\n" + "\n".join(parameter_lines)
        return message

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
