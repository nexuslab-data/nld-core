from nld.connector.base import ConnectorPlugin

from .s3_object_storage_connection import (
    S3ObjectStorageConnectionWrapper,
)
from .s3_object_storage_connector import (
    S3ObjectStorageConnector,
)
from .s3_object_storage_credential import (
    S3ObjectStorageCredential,
)
from .s3_object_storage_utils import (
    S3ObjectStorageUtils,
)
from .s3_structure import S3Structure

Plugin = ConnectorPlugin(
    connector_class=S3ObjectStorageConnector,
    connection_wrapper_class=S3ObjectStorageConnectionWrapper,
    credentials_class=S3ObjectStorageCredential,
)

__all__ = [
    "S3ObjectStorageConnectionWrapper",
    "S3ObjectStorageConnector",
    "S3ObjectStorageCredential",
    "S3ObjectStorageUtils",
    "S3Structure",
]
