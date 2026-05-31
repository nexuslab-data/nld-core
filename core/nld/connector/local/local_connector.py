import os
import shutil
from pathlib import Path

from nld.connector.base import DataConnector
from nld.connector.local.local_connection import LocalFileSystemConnectionWrapper


class LocalFileSystemConnector(DataConnector[LocalFileSystemConnectionWrapper]):
    """Connector for local filesystem read and write operations."""

    def read_file(self, file_path: str) -> str:
        """Read the contents of a local file."""
        with open(file_path, encoding="utf-8") as file_handle:
            return file_handle.read()

    def write_file(
        self,
        file_path: str,
        content: str,
    ) -> None:
        """Write content to a local file, creating parent directories."""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, mode="w", encoding="utf-8") as file_handle:
            file_handle.write(content)

    def check_if_file_exists(self, file_path: str) -> bool:
        """Check whether a file exists at the given path."""
        return os.path.isfile(file_path)

    def list_files(
        self,
        directory_path: str,
        recursive: bool = False,
    ) -> list[str]:
        """List files in a directory."""
        if not os.path.isdir(directory_path):
            return []

        if recursive:
            result: list[str] = []
            for root, _dirs, files in os.walk(directory_path):
                for file_name in files:
                    result.append(os.path.join(root, file_name))
            return result

        return [
            os.path.join(directory_path, entry)
            for entry in os.listdir(directory_path)
            if os.path.isfile(os.path.join(directory_path, entry))
        ]

    def delete_folder(self, folder_path: str) -> None:
        """Delete a folder and all its contents."""
        if os.path.isdir(folder_path):
            shutil.rmtree(folder_path)

    def move_folder(
        self,
        source_path: str,
        destination_path: str,
        keep_original: bool = False,
    ) -> None:
        """Move or copy a folder to a new location."""
        if keep_original:
            shutil.copytree(
                source_path,
                dst=destination_path,
                dirs_exist_ok=True,
            )
        else:
            shutil.move(
                source_path,
                dst=destination_path,
            )

    def ensure_directory_exists(self, directory_path: str) -> None:
        """Create directory and parents if they do not exist."""
        os.makedirs(directory_path, exist_ok=True)
