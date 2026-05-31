from typing import Any

from nld.logging import DebugEvent, ErrorEvent, InfoEvent

####################################################################
##                     Connection events                          ##
####################################################################


class ConnectionOpened(DebugEvent):
    def __init__(self, connection_name: str) -> None:
        super().__init__()
        self.connection_name = connection_name

    def code(self) -> str:
        return "C-101"

    def message(self) -> str:
        return f"Connection {self.connection_name} was opened successfully"


class ConnectionOpeningError(ErrorEvent):
    def __init__(self, connection_name: str, **kwargs: Any) -> None:
        super().__init__()
        self.connection_name = connection_name
        self.exc = kwargs.get("exc") if "exc" in kwargs else None

    def code(self) -> str:
        return "C-101"

    def message(self) -> str:
        if self.exc is not None:
            if hasattr(self.exc, "message"):
                return (
                    f"Connection '{self.connection_name}' could not be opened "
                    f"due to the error: {self.exc.__class__.__name__} "
                    f"with message '{self.exc.message}'"
                )
            else:
                return (
                    f"Connection '{self.connection_name}' could not be opened "
                    f"due to the error: {self.exc.__class__.__name__} "
                    f"with message '{self.exc}'"
                )
        return f"Connection '{self.connection_name}' could not be opened."


class ConnectionClosed(DebugEvent):
    def __init__(self, connection_name: str) -> None:
        super().__init__()
        self.connection_name = connection_name

    def code(self) -> str:
        return "C-102"

    def message(self) -> str:
        return f"Connection {self.connection_name} was closed successfully"


class ConnectionListDisplayed(InfoEvent):
    def __init__(self, connections: list[dict[str, Any]]) -> None:
        super().__init__()
        self.connections = connections

    def code(self) -> str:
        return "C-103"

    def message(self) -> str:
        if not self.connections:
            return "No connections available"

        connection_lines = []
        for conn in self.connections:
            profiles_str = ", ".join(conn["profiles"])
            connection_lines.append(
                f"  - {conn['name']} (type: {conn['type']}, profiles: {profiles_str})"
            )

        connections_str = "\n".join(connection_lines)
        return f"Available connections:\n{connections_str}"
