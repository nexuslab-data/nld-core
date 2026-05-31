from nld.connector.base import BaseConnectionCredential

from .azure_blob_storage_utils import (
    AzureBlobStorageUtils,
)


class AzureBlobStorageCredential(BaseConnectionCredential):
    storage_account_name: str | None
    sas_token: str | None

    @property
    def type(self) -> str:
        return "azure_blob_storage"

    @property
    def connect_string(self) -> str:
        if self.sas_token is not None:
            if self.storage_account_name is not None:
                return AzureBlobStorageUtils.create_connect_string_for_sas(
                    self.storage_account_name, self.sas_token
                )
        return ""
