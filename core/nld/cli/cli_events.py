from typing import Any

from nld.logging import ErrorEvent, InfoEvent
from nld.task import ExecutionInfo
from nld.utils import format_exception_traceback


class CommandStarted(InfoEvent):
    def __init__(
        self,
        exec_info: ExecutionInfo,
        parameters: dict[str, Any] | None = None,
    ):
        super().__init__()
        self.exec_info = exec_info
        self.parameters = parameters

    def code(self) -> str:
        return "CMD-001"

    def message(self) -> str:
        return self.exec_info.get_start_message(parameters=self.parameters)


class CommandCompleted(InfoEvent):
    def __init__(self, exec_info: ExecutionInfo):
        super().__init__()
        self.exec_info = exec_info

    def code(self) -> str:
        return "CMD-002"

    def message(self) -> str:
        return self.exec_info.get_completion_message()


class CommandRuntimeError(ErrorEvent):
    def __init__(self, e: Exception):
        self.e = e

    def code(self) -> str:
        return "CMD-091"

    def message(self) -> str:
        error_message = (
            str(self.e.message) if hasattr(self.e, "message") else str(self.e)
        )
        return (
            f"Runtime Error: {error_message}\n"
            f"{format_exception_traceback(exception=self.e)}"
        )
