from typing import Self

from nld.connector.base import ConnectionState, ConnectionWrapper
from nld.connector.local.local_credential import LocalFileSystemCredential
from nld.connector.local.local_utils import LOCAL_TYPE_NAME


class LocalFileSystemConnectionWrapper(
    ConnectionWrapper[LocalFileSystemCredential, None]
):
    """Connection wrapper for local filesystem operations."""

    @property
    def type(self) -> str:
        return LOCAL_TYPE_NAME

    def open(self) -> Self:
        self.state = ConnectionState.OPEN
        return self

    def _close_connection(self) -> bool:
        """No-op close since there is no real connection."""
        return True
