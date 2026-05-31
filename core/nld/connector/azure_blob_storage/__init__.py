from nld.connector.base import ConnectorPlugin

from .azure_blob_storage_connection import (
    AzureBlobStorageConnectionWrapper,
)
from .azure_blob_storage_connector import (
    AzureBlobStorageConnector,
)
from .azure_blob_storage_credential import (
    AzureBlobStorageCredential,
)
from .azure_blob_storage_utils import (
    AzureBlobStorageUtils,
)

Plugin = ConnectorPlugin(
    connector_class=AzureBlobStorageConnector,
    connection_wrapper_class=AzureBlobStorageConnectionWrapper,
    credentials_class=AzureBlobStorageCredential,
)

__all__ = [
    "AzureBlobStorageConnectionWrapper",
    "AzureBlobStorageConnector",
    "AzureBlobStorageCredential",
    "AzureBlobStorageUtils",
]
