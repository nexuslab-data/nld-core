from nld.logging import ErrorEvent, InfoEvent
from nld.task import ExecutionInfo


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
        return f"Runtime Error: {error_message}"
