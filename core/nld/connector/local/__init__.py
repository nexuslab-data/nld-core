from nld.connector.base import ConnectorPlugin

from .local_connection import LocalFileSystemConnectionWrapper
from .local_connector import LocalFileSystemConnector
from .local_credential import LocalFileSystemCredential

Plugin = ConnectorPlugin(
    connector_class=LocalFileSystemConnector,
    connection_wrapper_class=LocalFileSystemConnectionWrapper,
    credentials_class=LocalFileSystemCredential,
)

__all__ = [
    "LocalFileSystemConnectionWrapper",
    "LocalFileSystemConnector",
    "LocalFileSystemCredential",
]
