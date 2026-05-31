from nld.connector.base import BaseConnectionCredential

from .s3_utils import (
    S3_BLOB_STORAGE_TYPE_NAME,
)


class S3ObjectStorageCredential(BaseConnectionCredential):
    """
    Credential class for S3 Object Storage connections.

    Holds the connection parameters required to connect to an S3 Object Storage.
    """

    endpoint_url: str
    region_name: str
    access_key_id: str
    secret_access_key: str
    bucket_name: str

    @property
    def type(self) -> str:
        return S3_BLOB_STORAGE_TYPE_NAME
