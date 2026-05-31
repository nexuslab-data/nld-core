from nld.logging import DebugEvent, ErrorEvent


class ConnectorPluginImportError(ErrorEvent):
    def __init__(self, exc: str) -> None:
        super().__init__()
        self.exc = exc

    def code(self) -> str:
        return "IMP-191"

    def message(self) -> str:
        return f"{self.exc}"


class ConnectorPluginLoadError(ErrorEvent):
    def __init__(self, exc_info: str) -> None:
        super().__init__()
        self.exc_info = exc_info

    def code(self) -> str:
        return "IMP-192"

    def message(self) -> str:
        return f"{self.exc_info}"


class ConnectorPluginLoadSuccessful(DebugEvent):
    def __init__(self, type: str) -> None:
        super().__init__()
        self.type = type

    def code(self) -> str:
        return "IMP-101"

    def message(self) -> str:
        return f"Connection Adapter Plugin loaded successfully for {self.type}"
