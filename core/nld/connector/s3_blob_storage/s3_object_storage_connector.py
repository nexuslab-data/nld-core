from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd
from boto3.s3.transfer import TransferConfig

from nld.connector.base import ObjectStorageConnector

from .s3_object_storage_connection import (
    S3ObjectStorageConnectionWrapper,
)
from .s3_object_storage_utils import (
    S3ObjectStorageUtils,
)


class S3ObjectStorageConnector(
    ObjectStorageConnector[S3ObjectStorageConnectionWrapper]
):
    """
    Connector implementation for S3 Object Storage operations.

    Provides high-level methods for uploading, downloading, listing, and
    managing files and folders in S3 Object Storage.
    """

    def __init__(self, connection_wrapper: S3ObjectStorageConnectionWrapper) -> None:
        """
        Initialize the S3 Object Storage connector.

        Args:
            connection_wrapper: Wrapper managing the S3 connection
        """
        super().__init__(connection_wrapper)

    @classmethod
    def _detect_content_type(cls, path: Path) -> str:
        """
        Detect content type based on file extension.

        Args:
            path: File path to analyze

        Returns:
            MIME type string for the file
        """
        suffix = "".join(path.suffixes).lower()
        if suffix.endswith(".json"):
            return "application/json"
        if (
            suffix.endswith(".xml")
            or suffix.endswith(".txt")
            or suffix.endswith(".log")
        ):
            return "text/plain"
        if (
            suffix.endswith(".xml.gz")
            or suffix.endswith(".gz")
            or suffix.endswith(".tgz")
        ):
            return "application/gzip"
        return "application/octet-stream"

    def upload_file_from_local_path(
        self,
        local_file_path: str,
        obj_storage_path: str,
        **kwargs: Any,
    ) -> None:
        """
        Upload a file from local filesystem to S3 storage.

        Args:
            local_file_path: Path to the local file
            obj_storage_path: Destination path in S3 storage
        """
        self.assert_connection_is_opened()
        S3ObjectStorageUtils.upload_file_from_local_path(
            s3_client=self.connection_wrapper.connection,  # type: ignore[arg-type]
            bucket_name=self.connection_wrapper.credentials.bucket_name,
            local_path=local_file_path,
            s3_path=obj_storage_path,
        )

    def upload_files_from_local_paths(
        self,
        base_prefix: str,
        file_paths: Iterable[Path],
        cfg: TransferConfig | None = None,
        outer_workers: int = 16,
        **kwargs: Any,
    ) -> None:
        """
        Upload multiple files from local filesystem to S3 storage.

        Args:
            base_prefix: Base prefix for destination paths in S3
            file_paths: Iterable of local file paths to upload
            cfg: Optional transfer configuration settings
            outer_workers: Number of parallel workers for uploads
        """
        self.assert_connection_is_opened()
        S3ObjectStorageUtils.upload_files_from_local_paths(
            s3_client=self.connection_wrapper.connection,  # type: ignore[arg-type]
            bucket_name=self.connection_wrapper.credentials.bucket_name,
            base_prefix=base_prefix,
            file_paths=file_paths,
            cfg=cfg,
            outer_workers=outer_workers,
        )

    def download_file_to_local_path(
        self,
        obj_storage_path: str,
        local_file_path: str,
    ) -> None:
        """
        Download a file from S3 storage to local filesystem.

        Args:
            obj_storage_path: Source path in S3 storage
            local_file_path: Destination path on local filesystem
        """
        self.assert_connection_is_opened()
        S3ObjectStorageUtils.download_file_to_local_path(
            s3_client=self.connection_wrapper.connection,  # type: ignore[arg-type]
            bucket=self.connection_wrapper.credentials.bucket_name,
            s3_path=obj_storage_path,
            local_path=local_file_path,
        )

    def check_if_file_exists(
        self,
        obj_storage_path: str,
    ) -> bool:
        """
        Check if a file exists at the specified S3 path.

        Args:
            obj_storage_path: Path in S3 storage to check

        Returns:
            True if file exists, False otherwise
        """
        self.assert_connection_is_opened()
        return S3ObjectStorageUtils.check_if_file_exists(
            s3_client=self.connection_wrapper.connection,  # type: ignore[arg-type]
            bucket=self.connection_wrapper.credentials.bucket_name,
            s3_path=obj_storage_path,
        )

    def upload_df_to_csv_file(
        self,
        df: pd.DataFrame,
        obj_storage_path: str,
        **kwargs: Any,
    ) -> None:
        """
        Upload a pandas DataFrame as a CSV file to S3 storage.

        Args:
            df: DataFrame to upload
            obj_storage_path: Destination path in S3 storage
        """
        self.assert_connection_is_opened()
        S3ObjectStorageUtils.upload_df_to_csv_file(
            df,
            s3_client=self.connection_wrapper.connection,  # type: ignore[arg-type]
            bucket_name=self.connection_wrapper.credentials.bucket_name,
            s3_path=obj_storage_path,
        )

    def _get_blobs_list(
        self,
        prefix: str | None = None,
        **kwargs: Any,
    ) -> list[str]:
        """
        Get list of blobs at a specific prefix level.

        Args:
            prefix: Optional prefix to filter blobs

        Returns:
            List of blob paths including folders
        """
        self.assert_connection_is_opened()
        return S3ObjectStorageUtils.list_blobs(
            s3_client=self.connection_wrapper.connection,  # type: ignore[arg-type]
            bucket=self.connection_wrapper.credentials.bucket_name,
            prefix=prefix,
            recursive=False,
            include_folders=True,
        )

    def _get_blobs_list_recursive(
        self,
        prefix: str | None = None,
        **kwargs: Any,
    ) -> list[str]:
        """
        Get recursive list of all blobs under a prefix.

        Args:
            prefix: Optional prefix to filter blobs

        Returns:
            List of all blob paths excluding folders
        """
        self.assert_connection_is_opened()
        return S3ObjectStorageUtils.list_blobs(
            s3_client=self.connection_wrapper.connection,  # type: ignore[arg-type]
            bucket=self.connection_wrapper.credentials.bucket_name,
            prefix=prefix,
            recursive=True,
            include_folders=False,
        )

    def _delete_blob_folder(self, folder_path: str, **kwargs: Any) -> dict[str, int]:
        """
        Delete all blobs in a folder including versions.

        Args:
            folder_path: Folder prefix to delete

        Returns:
            Dictionary with counts of deleted objects
        """
        self.assert_connection_is_opened()
        return S3ObjectStorageUtils.delete_blob_folder(
            s3_client=self.connection_wrapper.connection,  # type: ignore[arg-type]
            bucket=self.connection_wrapper.credentials.bucket_name,
            prefix=folder_path,
            include_placeholder=True,
            versioned=True,
        )

    def _move_blob_folder(
        self,
        src_folder_path: str,
        dst_folder_path: str,
        keep_original: bool = False,
        **kwargs: Any,
    ) -> None:
        """
        Move all blobs from source folder to destination folder.

        Args:
            src_folder_path: Source folder prefix
            dst_folder_path: Destination folder prefix
            keep_original: If True, keep original files after moving
        """
        self.assert_connection_is_opened()
        return S3ObjectStorageUtils.move_folder(
            s3_client=self.connection_wrapper.connection,  # type: ignore[arg-type]
            bucket=self.connection_wrapper.credentials.bucket_name,
            src_prefix=src_folder_path,
            dst_prefix=dst_folder_path,
            overwrite=False,
            keep_original=keep_original,
        )
