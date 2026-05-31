from azure.storage.blob import BlobClient, BlobPrefix, ContainerClient

from nld.connector.base.connector import DataConnector

from .azure_blob_storage_connection import (
    AzureBlobStorageConnectionWrapper,
)
from .azure_blob_storage_utils import (
    AzureBlobStorageUtils,
)


class AzureBlobStorageConnector(DataConnector[AzureBlobStorageConnectionWrapper]):
    def __init__(self, connection_wrapper: AzureBlobStorageConnectionWrapper) -> None:
        super().__init__(connection_wrapper)

    def _get_container_client(self, container_name: str) -> ContainerClient:
        assert self.connection_wrapper.connection is not None
        return self.connection_wrapper.connection.get_container_client(container_name)

    def _get_blob_client(self, container_name: str, blob_name: str) -> BlobClient:
        assert self.connection_wrapper.connection is not None
        return self.connection_wrapper.connection.get_blob_client(
            container=container_name, blob=blob_name
        )

    def _load_from_local_path(
        self,
        local_file_path: str,
        container_name: str,
        blob_name: str,
    ) -> None:
        assert self.connection_wrapper is not None
        assert self.connection_wrapper.connection is not None
        if not self.connection_is_opened():
            self.log_debug("Azure Blob Storage is not opened")
            raise RuntimeError("Azure Blob Storage is not opened")
        AzureBlobStorageUtils.load_from_local_path(
            self.connection_wrapper.connection,
            local_file_path,
            container_name,
            blob_name,
        )

    def _get_blobs_list(
        self,
        container_name: str,
        prefix: str | None = None,
        include: list[str] | None = None,
        delimiter: str = "/",
    ) -> list[str]:
        container = self._get_container_client(container_name)
        blob_list = []
        blobs = container.walk_blobs(
            name_starts_with=prefix,
            include=include,
            delimiter=delimiter,
        )
        for blob in blobs:
            blob_list.append(blob.name)
        return blob_list

    def _get_blobs_list_recursive(
        self,
        container_name: str,
        prefix: str | None = None,
        include: list[str] | None = None,
        delimiter: str = "/",
    ) -> list[str]:
        container = self._get_container_client(container_name)
        blob_list = []
        blobs = container.walk_blobs(
            name_starts_with=prefix,
            include=include,
            delimiter=delimiter,
        )
        for blob in blobs:
            if isinstance(blob, BlobPrefix):
                blob_list.extend(
                    self._get_blobs_list_recursive(
                        container_name=container_name,
                        prefix=blob.name,
                        include=include,
                        delimiter=delimiter,
                    )
                )
            else:
                blob_list.append(blob.name)
        return blob_list

    def _delete_blob_folder(self, container_name: str, folder_name: str) -> None:
        assert self.connection_wrapper is not None
        assert self.connection_wrapper.connection is not None
        if not self.connection_is_opened():
            self.log_debug("Azure Blob Storage is not opened")
            raise RuntimeError("Azure Blob Storage is not opened")
        for blob in self._get_blobs_list_recursive(container_name, folder_name):
            self._get_blob_client(container_name, blob).delete_blob()
        return None
