from typing import Self, cast

import boto3
from botocore.config import Config as BotoConfig
from mypy_boto3_s3.client import S3Client

from nld.connector.base import ConnectionState, ConnectionWrapper
from nld.exceptions import ConnectionCouldNotBeOpenedException

from .s3_object_storage_credential import (
    S3ObjectStorageCredential,
)
from .s3_utils import (
    S3_BLOB_STORAGE_TYPE_NAME,
)


class S3ObjectStorageConnectionWrapper(
    ConnectionWrapper[S3ObjectStorageCredential, S3Client]
):
    """
    Connection wrapper for S3 Object Storage client.

    Manages the lifecycle and state of boto3 S3 client connections,
    handling session creation and connection initialization.
    """

    session: boto3.session.Session | None = None

    def __init__(
        self,
        name: str,
        credentials: S3ObjectStorageCredential,
        state: ConnectionState = ConnectionState.INIT,
        connection: S3Client | None = None,
    ) -> None:
        """
        Initialize the S3 Object Storage connection wrapper.

        Args:
            name: Connection name identifier
            credentials: S3 credentials for authentication
            state: Initial connection state
            connection: Optional existing S3 client instance
        """
        super().__init__(
            name=name,
            credentials=credentials,
            state=state,
            connection=connection,
        )

    @property
    def type(self) -> str:
        """
        Return the connection type identifier.

        Returns:
            Connection type name for S3 blob storage
        """
        return S3_BLOB_STORAGE_TYPE_NAME

    def open(self) -> Self:
        """
        Open the S3 Object Storage connection.

        Creates a boto3 session and S3 client using the provided
        credentials and configures connection parameters.

        Returns:
            Self instance with opened connection

        Raises:
            ConnectionCouldNotBeOpenedException: If connection fails to open
        """
        if self.credentials is not None:
            self.logger.info(f"S3 Object Storage Connection {self.name} opening")
            self.session = cast(
                boto3.session.Session,
                boto3.session.Session(
                    aws_access_key_id=self.credentials.access_key_id,
                    aws_secret_access_key=self.credentials.secret_access_key,
                    region_name=self.credentials.region_name or None,
                ),
            )
            self.connection = cast(
                S3Client,
                self.session.client(
                    service_name="s3",
                    endpoint_url=self.credentials.endpoint_url,
                    config=BotoConfig(
                        retries={"max_attempts": 8, "mode": "standard"},
                        tcp_keepalive=True,
                    ),
                ),
            )

            self.state = ConnectionState.OPEN

        if self.state != ConnectionState.OPEN:
            raise ConnectionCouldNotBeOpenedException(self.name)
        return self
