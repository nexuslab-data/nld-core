from nld.connector.base import BaseConnectionCredential
from nld.connector.local.local_utils import LOCAL_TYPE_NAME


class LocalFileSystemCredential(BaseConnectionCredential):
    """Credential for local filesystem connector."""

    base_path: str = ""

    @property
    def type(self) -> str:
        return LOCAL_TYPE_NAME
