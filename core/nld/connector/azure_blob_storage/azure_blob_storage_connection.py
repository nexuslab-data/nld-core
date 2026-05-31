from typing import Self

from azure.storage.blob import BlobServiceClient

from nld.connector.base import ConnectionState, ConnectionWrapper
from nld.exceptions import ConnectionCouldNotBeOpenedException

from .azure_blob_storage_credential import (
    AzureBlobStorageCredential,
)


class AzureBlobStorageConnectionWrapper(
    ConnectionWrapper[AzureBlobStorageCredential, BlobServiceClient]
):
    def __init__(
        self,
        name: str,
        credentials: AzureBlobStorageCredential,
        state: ConnectionState = ConnectionState.INIT,
        connection: BlobServiceClient | None = None,
    ) -> None:
        super().__init__(
            name=name,
            credentials=credentials,
            state=state,
            connection=connection,
        )

    @property
    def type(self) -> str:
        return "azure_blob_storage"

    def open(self) -> Self:
        if self.credentials is not None:
            connect_string = self.credentials.connect_string
            if connect_string != "":
                self.state = ConnectionState.OPEN
                self.connection = BlobServiceClient.from_connection_string(
                    connect_string
                )
        if self.state != ConnectionState.OPEN:
            raise ConnectionCouldNotBeOpenedException(self.name)
        return self
