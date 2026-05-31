from nld.logging import DebugEvent, ErrorEvent, InfoEvent, WarnEvent


class IncrementalParameterIgnored(WarnEvent):
    def __init__(
        self,
        data_load_strategy: str,
        parameter_name: str,
    ) -> None:
        super().__init__()
        self.data_load_strategy = data_load_strategy
        self.parameter_name = parameter_name

    def code(self) -> str:
        return "INC-001"

    def message(self) -> str:
        return (
            f"'{self.parameter_name}' parameter is set but flow loading "
            f"strategy is {self.data_load_strategy}. Parameter will be ignored."
        )


class IncrementalMissingParameter(ErrorEvent):
    def __init__(
        self,
        data_load_strategy: str,
        parameter_names: list[str],
    ) -> None:
        super().__init__()
        self.data_load_strategy = data_load_strategy
        self.parameter_names = parameter_names

    def code(self) -> str:
        return "INC-002"

    def message(self) -> str:
        return (
            f"Flow loading strategy {self.data_load_strategy} requires at least one "
            f"of the parameters {', '.join(self.parameter_names)}. "
            f"Please provide them to execute flow in this loading strategy."
        )


class IncrementalBackendLoadSuccessful(DebugEvent):
    """Event for successful incremental backend manager loading"""

    def __init__(self, backend_type: str) -> None:
        super().__init__()
        self.backend_type = backend_type

    def code(self) -> str:
        return "INC-BACKEND-101"

    def message(self) -> str:
        return (
            f"Incremental backend manager for '{self.backend_type}' loaded successfully"
        )


class IncrementalBackendEngineInitialized(InfoEvent):
    """Event for engine-specific incremental backend manager initialization."""

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
        return "INC-BACKEND-102"

    def message(self) -> str:
        return (
            f"Incremental state backend manager '{self.manager_class}' initialized "
            f"(backend='{self.backend_type}', engine='{self.engine}')"
        )


class IncrementalBackendImportError(ErrorEvent):
    """Event for incremental backend import error"""

    def __init__(self, backend_type: str, exc: str) -> None:
        super().__init__()
        self.backend_type = backend_type
        self.exc = exc

    def code(self) -> str:
        return "INC-BACKEND-191"

    def message(self) -> str:
        return (
            f"Failed to import incremental backend manager "
            f"for '{self.backend_type}': {self.exc}"
        )


class IncrementalBackendLoadError(ErrorEvent):
    """Event for incremental backend loading error"""

    def __init__(self, exc_info: str) -> None:
        super().__init__()
        self.exc_info = exc_info

    def code(self) -> str:
        return "INC-BACKEND-192"

    def message(self) -> str:
        return f"Error loading incremental backend manager: {self.exc_info}"


class IncrementalStateManagerLoadSuccessful(DebugEvent):
    """Event for successful incremental state manager loading"""

    def __init__(self, incremental_type: str) -> None:
        super().__init__()
        self.incremental_type = incremental_type

    def code(self) -> str:
        return "INC-STATE-101"

    def message(self) -> str:
        return (
            f"Incremental state manager for '{self.incremental_type}' "
            f"loaded successfully"
        )
