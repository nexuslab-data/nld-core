import abc
import os
import shutil
from pathlib import Path
from typing import Any

from nld.connector.local import LocalFileSystemConnector
from nld.flow.backend.utils import BackendStandardFolderNames


class LocalBackendMixin(abc.ABC):
    """
    Mixin providing common local filesystem backend functionality.

    Provides path helpers and file operations for backends that persist
    state to the local filesystem. Unlike S3, no local_state_dir or
    processing_sub_folder_name flow parameters are needed since the
    local path IS the storage.
    """

    backend_connector: LocalFileSystemConnector
    parameters: dict[str, Any]

    @property
    def backend_root_path(self) -> str:
        return self.parameters["backend_root_path"]  # type: ignore[no-any-return]

    @property
    def backend_state_root_path(self) -> str:
        return os.path.join(self.backend_root_path, BackendStandardFolderNames.STATE)

    @property
    def backend_state_for_processing_path(self) -> str:
        return os.path.join(
            self.backend_root_path,
            "processing",
            BackendStandardFolderNames.STATE,
        )

    def _write_file_to_state_at_root_folder(
        self,
        local_path: Path,
    ) -> None:
        """Copy a local file into the state root folder."""
        destination_dir = self.backend_state_root_path
        os.makedirs(destination_dir, exist_ok=True)
        shutil.copy2(
            str(local_path),
            dst=os.path.join(destination_dir, local_path.name),
        )

    def _write_file_to_state_in_process_folder(
        self,
        local_path: Path,
    ) -> None:
        """Copy a local file into the processing state folder."""
        destination_dir = self.backend_state_for_processing_path
        os.makedirs(destination_dir, exist_ok=True)
        shutil.copy2(
            str(local_path),
            dst=os.path.join(destination_dir, local_path.name),
        )
