from nld.logging import DebugEvent, ErrorEvent


class StateManagerLoadSuccessful(DebugEvent):
    """Event for successful state manager loading"""

    def __init__(self, incremental_type: str) -> None:
        super().__init__()
        self.incremental_type = incremental_type

    def code(self) -> str:
        return "STATE-MANAGER-101"

    def message(self) -> str:
        return f"State manager for '{self.incremental_type}' loaded successfully"


class StateManagerImportError(ErrorEvent):
    """Event for state manager import error"""

    def __init__(self, incremental_type: str, exc: str) -> None:
        super().__init__()
        self.incremental_type = incremental_type
        self.exc = exc

    def code(self) -> str:
        return "STATE-MANAGER-191"

    def message(self) -> str:
        return (
            f"Failed to import state manager for '{self.incremental_type}': {self.exc}"
        )


class StateManagerLoadError(ErrorEvent):
    """Event for state manager loading error"""

    def __init__(self, exc_info: str) -> None:
        super().__init__()
        self.exc_info = exc_info

    def code(self) -> str:
        return "STATE-MANAGER-192"

    def message(self) -> str:
        return f"Error loading state manager: {self.exc_info}"
