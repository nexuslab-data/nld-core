from nld.logging import ErrorEvent, InfoEvent
from nld.task.execution import ExecutionInfo
from nld.utils.string_utils import un_camel

####################################################################
##                     Execution events                           ##
####################################################################


class ExecutionStarted(InfoEvent):
    def __init__(self, exec_info: ExecutionInfo):
        super().__init__()
        self.exec_info = exec_info

    def code(self) -> str:
        return "EXEC-001"

    def message(self) -> str:
        return self.exec_info.get_start_message()


class ExecutionCompleted(InfoEvent):
    def __init__(self, exec_info: ExecutionInfo):
        super().__init__()
        self.exec_info = exec_info

    def code(self) -> str:
        return "EXEC-002"

    def message(self) -> str:
        return self.exec_info.get_completion_message()


class ExecutionRuntimeError(ErrorEvent):
    def __init__(self, e: Exception):
        super().__init__()
        self.e = e

    def code(self) -> str:
        return "EXEC-091"

    def message(self) -> str:
        return f"Command runtime exception {un_camel(type(self.e).__name__)} " + (
            f'with message "{str(self.e.message)}".\n'
            if hasattr(self.e, "message")
            else ""
        )


class ProjectLoadedSuccessfully(InfoEvent):
    def __init__(self) -> None:
        super().__init__()

    def code(self) -> str:
        return "EXEC-010"

    def message(self) -> str:
        return "Project was loaded successfully"


class ConnectionFactoryLoadedSuccessfully(InfoEvent):
    def __init__(self) -> None:
        super().__init__()

    def code(self) -> str:
        return "EXEC-011"

    def message(self) -> str:
        return "Connection Factory was loaded successfully"
