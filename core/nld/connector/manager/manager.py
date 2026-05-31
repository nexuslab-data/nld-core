from typing import Any

from nld.connector.base import DataConnector
from nld.connector.base.exceptions import (
    ConnectorAlreadyAvailableException,
    NoConnectorAvailableException,
)
from nld.utils.mixin import NldMixIn


class ConnectorManager(NldMixIn):
    def __init__(self) -> None:
        super().__init__()
        self.connectors: dict[str, DataConnector[Any]] = {}

    def has_connector(self, name: str) -> bool:
        return name in list(self.connectors.keys())

    def add_connector(
        self,
        name: str,
        connector: DataConnector[Any],
    ) -> None:
        if name in list(self.connectors.keys()):
            raise ConnectorAlreadyAvailableException(name)
        self.connectors.update({name: connector})

    def get_connector_names(self) -> list[str]:
        return list(self.connectors.keys())

    def get_connector(self, name: str) -> DataConnector[Any]:
        if name not in list(self.connectors.keys()):
            raise NoConnectorAvailableException(name)
        return self.connectors[name]

    def open_connection(self, name: str) -> None:
        self.get_connector(name).open_connection()

    def close_connection(self, name: str) -> bool:
        service = self.get_connector(name)
        service.close_connection()
        return service.connection_wrapper.is_closed()  # type: ignore[no-any-return]

    def close_all_connections(self) -> bool:
        all_connections_closed = True
        for service_name in self.get_connector_names():
            if not self.close_connection(service_name):
                all_connections_closed = False
        return all_connections_closed
