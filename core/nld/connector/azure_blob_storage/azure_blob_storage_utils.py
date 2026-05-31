from azure.storage.blob import BlobPrefix, BlobServiceClient, ContainerClient


class AzureBlobStorageUtils:
    def __init__(self) -> None:
        pass

    @classmethod
    def load_from_local_path(
        cls,
        blob_service_client: BlobServiceClient,
        local_file_path: str,
        container_name: str,
        blob_name: str,
    ) -> None:
        blob_client = blob_service_client.get_blob_client(
            container=container_name, blob=blob_name
        )
        with open(local_file_path, "rb") as data:
            blob_client.upload_blob(data=data)

    @classmethod
    def create_connect_string_for_sas(
        cls, storage_account_name: str, sas_token: str
    ) -> str:
        connect_string = (
            f"BlobEndpoint=https://{storage_account_name}.blob.core.windows.net"
            + f";QueueEndpoint=https://{storage_account_name}.queue.core.windows.net"
            + f";FileEndpoint=https://{storage_account_name}.queue.core.windows.net"
            + f";TableEndpoint=https://{storage_account_name}.queue.core.windows.net"
            + f";SharedAccessSignature={sas_token}"
        )
        return connect_string

    @classmethod
    def print_blobs_hierarchical(
        cls,
        container_client: ContainerClient,
        prefix: str,
        depth: int,
        indent: str = "  ",
    ) -> None:
        for blob in container_client.walk_blobs(name_starts_with=prefix, delimiter="/"):
            if isinstance(blob, BlobPrefix):
                # Indentation is only added to show nesting in the output
                print(f"{indent * depth}{blob.name}")
                depth += 1
                cls.print_blobs_hierarchical(
                    container_client, prefix=blob.name, depth=depth
                )
            else:
                print(f"{indent * depth}{blob.name}")

    @classmethod
    def extract_blob_path_as_tuple(cls, azure_blob_path: str) -> tuple[str, str, str]:
        if azure_blob_path.find("azure://") == -1:
            raise ValueError("Azure Blob Path should start with azure://")
        if azure_blob_path.find(".blob.core.windows.net/") == -1:
            raise ValueError('Azure Blob Path should contain ".blob.core.windows.net/"')
        storage_account_name, blob_path_incl_container = (
            azure_blob_path.split("azure://")[1]
        ).split(".blob.core.windows.net/")
        container_name, blob_path = blob_path_incl_container.split("/", 1)
        return storage_account_name, container_name, blob_path
