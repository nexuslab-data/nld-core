from nld.logging import DebugEvent, ErrorEvent, InfoEvent


class ExecutionBackendLoadSuccessful(DebugEvent):
    """Event for successful backend manager loading"""

    def __init__(self, backend_type: str) -> None:
        super().__init__()
        self.backend_type = backend_type

    def code(self) -> str:
        return "EXEC-BACKEND-101"

    def message(self) -> str:
        return (
            f"Execution backend manager for '{self.backend_type}' loaded successfully"
        )


class ExecutionBackendEngineInitialized(InfoEvent):
    """Event for engine-specific execution backend manager initialization."""

    def __init__(
        self,
        backend_type: str,
        engine: str,
        manager_class: str,
    ) -> None:
        super().__init__()
        self.backend_type = backend_type
        self.engine = engine
        self.manager_class = manager_class

    def code(self) -> str:
        return "EXEC-BACKEND-102"

    def message(self) -> str:
        return (
            f"Execution state backend manager '{self.manager_class}' initialized "
            f"(backend='{self.backend_type}', engine='{self.engine}')"
        )


class ExecutionBackendImportError(ErrorEvent):
    """Event for backend import error"""

    def __init__(self, backend_type: str, exc: str) -> None:
        super().__init__()
        self.backend_type = backend_type
        self.exc = exc

    def code(self) -> str:
        return "EXEC-BACKEND-191"

    def message(self) -> str:
        return (
            f"Failed to import execution backend manager "
            f"for '{self.backend_type}': {self.exc}"
        )


class ExecutionBackendLoadError(ErrorEvent):
    """Event for backend loading error"""

    def __init__(self, exc_info: str) -> None:
        super().__init__()
        self.exc_info = exc_info

    def code(self) -> str:
        return "EXEC-BACKEND-192"

    def message(self) -> str:
        return f"Error loading execution backend manager: {self.exc_info}"
