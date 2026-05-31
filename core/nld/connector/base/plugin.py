from typing import Any

from .connection import ConnectionWrapper
from .connector import DataConnector


class ConnectorPlugin[
    DATA_CONNECTOR: DataConnector[Any],
    CONNECTION_WRAPPER: ConnectionWrapper[Any, Any],
    CREDENTIAL_TYPE,
]:
    """Defines the basic requirements for a connector plugin"""

    def __init__(
        self,
        connector_class: type[DATA_CONNECTOR],
        connection_wrapper_class: type[CONNECTION_WRAPPER],
        credentials_class: type[CREDENTIAL_TYPE],
        structure_class_path: str | None = None,
    ):
        self.connector_class: type[DATA_CONNECTOR] = connector_class
        self.connection_wrapper_class: type[CONNECTION_WRAPPER] = (
            connection_wrapper_class
        )
        self.credentials_class: type[CREDENTIAL_TYPE] = credentials_class
        self.structure_class_path: str | None = structure_class_path

    def create_new_credentials(
        self, credentials_dict: dict[str, Any]
    ) -> CREDENTIAL_TYPE:
        return self.credentials_class(**credentials_dict)

    def create_new_connection_wrapper(
        self, name: str, credentials_dict: dict[str, Any]
    ) -> CONNECTION_WRAPPER:
        return self.connection_wrapper_class(
            name=name,
            credentials=self.create_new_credentials(credentials_dict),
        )

    def create_new_connector(
        self,
        name: str,
        credentials_dict: dict[str, Any],
        custom_connector_class: type[DATA_CONNECTOR] | None = None,
    ) -> DATA_CONNECTOR:
        if custom_connector_class is not None:
            assert issubclass(custom_connector_class, self.connector_class), (
                f"Creation of connector for class {custom_connector_class.__name__}"
                f" is not possible, as this class is not a sub class of plugin "
                f"service class {self.connector_class.__name__}"
            )
            connector_class_to_build = custom_connector_class
        else:
            connector_class_to_build = self.connector_class
        return connector_class_to_build(
            connection_wrapper=self.create_new_connection_wrapper(
                name,
                credentials_dict=credentials_dict,
            ),
        )
