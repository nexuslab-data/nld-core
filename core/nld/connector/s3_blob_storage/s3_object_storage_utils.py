import io
import mimetypes
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd
from boto3.s3.transfer import S3Transfer, TransferConfig
from botocore.exceptions import ClientError
from mypy_boto3_s3.client import S3Client


class S3ObjectStorageUtils:
    """
    Utility class for S3 Object Storage operations.

    Provides low-level methods for file transfers, blob management, and
    folder operations on S3 Object Storage.
    """

    def __init__(self) -> None:
        """Initialize the S3 Object Storage utilities."""

    @classmethod
    def upload_file_from_local_path(
        cls,
        s3_client: S3Client,
        bucket_name: str,
        local_path: str | Path,
        s3_path: str | None = None,
        cfg: TransferConfig | None = None,
    ) -> None:
        """
        Upload a single local file to S3 Object Storage.

        Args:
            s3_client: Boto3 S3 client instance
            bucket_name: Target S3 bucket name
            local_path: Path to local file to upload
            s3_path: Optional destination path in S3
            cfg: Optional transfer configuration settings
        """
        local_path_obj = Path(local_path)
        if not local_path_obj.is_file():
            raise FileNotFoundError(local_path_obj)
        s3_path = s3_path or local_path_obj.name

        # Default the transfer configuration if not provided.
        cfg = cfg or cls.create_transfer_config()

        # Infer content type for web assets and proper rendering.
        extra_args = {}
        content_type, _ = mimetypes.guess_type(str(local_path))
        if content_type:
            extra_args["ContentType"] = content_type

        # The upload_file method handles multipart uploads automatically.
        s3_client.upload_file(
            str(local_path),
            bucket_name,
            s3_path,
            ExtraArgs=extra_args,
            Config=cfg,
        )
        print(f"Uploaded {local_path} -> s3://{bucket_name}/{s3_path}")

    @classmethod
    def upload_files_from_local_paths(
        cls,
        s3_client: S3Client,
        bucket_name: str,
        base_prefix: str,
        file_paths: Iterable[Path],
        cfg: TransferConfig | None = None,
        outer_workers: int = 16,
    ) -> None:
        """
        Upload multiple files from local filesystem to S3 storage.

        Args:
            s3_client: Boto3 S3 client instance
            bucket_name: Target S3 bucket name
            base_prefix: Base prefix for destination paths in S3
            file_paths: Iterable of local file paths to upload
            cfg: Optional transfer configuration settings
            outer_workers: Number of parallel workers for uploads
        """
        futures = []
        with ThreadPoolExecutor(max_workers=outer_workers) as executor:
            for file_path in file_paths:
                key = f"{base_prefix}{file_path.name}"
                futures.append(
                    executor.submit(
                        cls.upload_file_from_local_path,
                        s3_client=s3_client,
                        bucket_name=bucket_name,
                        local_path=file_path,
                        s3_path=key,
                        cfg=cfg,
                    )
                )
            for future in as_completed(futures):
                _ = future.result()

    @staticmethod
    def download_file_to_local_path(
        s3_client: S3Client,
        bucket: str,
        s3_path: str,
        local_path: str,
    ) -> None:
        """
        Download a single file from S3 Object Storage to local filesystem.

        Args:
            s3_client: Boto3 S3 client instance
            bucket: S3 bucket name
            s3_path: Path to file in S3
            local_path: Destination path on local filesystem

        Raises:
            FileNotFoundError: If the S3 object does not exist
        """
        local_path_obj = Path(local_path)
        local_path_obj.parent.mkdir(parents=True, exist_ok=True)

        try:
            s3_client.download_file(
                bucket,
                s3_path,
                str(local_path_obj),
            )
            print(f"Downloaded {local_path_obj} -> s3://{bucket}/{s3_path}")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "404":
                raise FileNotFoundError(f"s3://{bucket}/{s3_path}") from e
            else:
                raise

    @staticmethod
    def check_if_file_exists(
        s3_client: S3Client,
        bucket: str,
        s3_path: str,
    ) -> bool:
        """
        Check if a file exists at the provided path.

        Args:
            s3_client: Boto3 S3 client instance
            bucket: S3 bucket name
            s3_path: Path to check in S3

        Returns:
            True if file exists, False otherwise
        """
        try:
            s3_client.head_object(
                Bucket=bucket,
                Key=s3_path,
            )
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "404":
                return False
            else:
                raise

    @staticmethod
    def upload_df_to_csv_file(
        df: pd.DataFrame,
        s3_client: S3Client,
        bucket_name: str,
        s3_path: str,
    ) -> None:
        """
        Upload a pandas DataFrame as a CSV file to S3.

        Args:
            df: DataFrame to upload
            s3_client: Boto3 S3 client instance
            bucket_name: S3 bucket name
            s3_path: Destination path in S3
        """
        content_type = "text/csv"

        csv_options: dict[str, Any] = {}
        text_buf = io.StringIO()
        df.to_csv(text_buf, **csv_options)
        buf = io.BytesIO(text_buf.getvalue().encode("utf-8"))

        buf.seek(0)

        s3_client.put_object(
            Bucket=bucket_name,
            Key=s3_path,
            Body=buf,
            ContentType=content_type,
        )
        print(f"Created object on bucket {bucket_name} at location {s3_path}")

    @classmethod
    def list_blobs(
        cls,
        s3_client: S3Client,
        bucket: str,
        prefix: str | None = None,
        recursive: bool = True,
        include_folders: bool = True,
    ) -> list[str]:
        """
        Yield object metadata dicts from an S3 bucket.

        :param s3_client: boto3 S3 client
        :param bucket: bucket name
        :param prefix: only list keys starting with this prefix (e.g., "data/")
        :param recursive: if False, returns only one level (Delimiter='/')
        :param include_folders: when recursive=False, also include 'folder/'
            strings from CommonPrefixes
        :return: list of strings (keys and optionally folder names with '/')
        """
        paginator = s3_client.get_paginator("list_objects_v2")
        kwargs = {
            "Bucket": bucket,
            "Prefix": prefix or "",
        }
        if not recursive:
            kwargs["Delimiter"] = "/"

        results: list[str] = []
        for page in paginator.paginate(**kwargs):  # type: ignore[arg-type]
            # List of object keys.
            results.extend(obj["Key"] for obj in page.get("Contents", []))

            # Optional folders at this level for non-recursive listing.
            if include_folders and not recursive:
                results.extend(cp["Prefix"] for cp in page.get("CommonPrefixes", []))

        return results

    @staticmethod
    def _batch_delete(
        s3_client: S3Client,
        bucket: str,
        objects: list[dict[str, Any]],
    ) -> int:
        """
        Delete objects in chunks of 1000 entries.

        Args:
            s3_client: Boto3 S3 client instance
            bucket: S3 bucket name
            objects: List of object dictionaries to delete

        Returns:
            Number of successfully deleted objects
        """
        deleted = 0
        for i in range(0, len(objects), 1000):
            chunk = {"Objects": objects[i : i + 1000], "Quiet": True}
            resp = s3_client.delete_objects(
                Bucket=bucket,
                Delete=chunk,  # type: ignore[arg-type]
            )
            deleted += len(resp.get("Deleted", []))
        return deleted

    @staticmethod
    def create_transfer_config(
        threshold_mb: int = 64,
        part_size_mb: int = 32,
        max_concurrency: int = 10,
    ) -> TransferConfig:
        """
        Create a transfer configuration for S3 operations.

        Args:
            threshold_mb: Multipart upload threshold in megabytes
            part_size_mb: Size of each multipart chunk in megabytes
            max_concurrency: Maximum number of concurrent transfers

        Returns:
            Configured TransferConfig instance
        """
        return TransferConfig(
            multipart_threshold=threshold_mb * 1024**2,
            multipart_chunksize=part_size_mb * 1024**2,
            max_concurrency=max_concurrency,
            use_threads=True,
        )

    @classmethod
    def move_file(
        cls,
        s3_client: S3Client,
        bucket: str,
        src_key: str,
        dst_key: str,
        overwrite: bool = False,
        keep_original: bool = True,
        transfer_cfg: TransferConfig | None = None,
    ) -> None:
        """
        Move a single object within a bucket by copying then deleting.

        :param s3_client: boto3 S3 client
        :param bucket: bucket name
        :param src_key: e.g. 'landing/file.csv'
        :param dst_key: e.g. 'process/file.csv'
        :param overwrite: if False and destination exists, raise FileExistsError
        :param keep_original: if True, source blobs are deleted
        :param transfer_cfg: Transfer configuration

        """
        _transfer_cfg = (
            cls.create_transfer_config() if transfer_cfg is None else transfer_cfg
        )

        # Step one:verify that source object exists.
        src_head = s3_client.head_object(
            Bucket=bucket,
            Key=src_key,
        )

        # Step two:guard against accidental overwrite of destination.
        if not overwrite:
            try:
                s3_client.head_object(
                    Bucket=bucket,
                    Key=dst_key,
                )
                raise FileExistsError(
                    f"Destination already exists: s3://{bucket}/{dst_key}"
                )
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") != "404":
                    raise

        # Step three:perform server-side copy operation preserving metadata.
        s3_client.copy(
            {"Bucket": bucket, "Key": src_key},
            Bucket=bucket,
            Key=dst_key,
            ExtraArgs={"MetadataDirective": "COPY", "ACL": "private"},
            Config=_transfer_cfg,
        )

        # Step four:verify copy integrity by comparing file sizes.
        dst_head = s3_client.head_object(
            Bucket=bucket,
            Key=dst_key,
        )
        if dst_head["ContentLength"] != src_head["ContentLength"]:
            # Best effort integrity check to prevent data loss.
            raise OSError(
                "Size mismatch after copy; aborting delete to avoid data loss "
                f"(src={src_head['ContentLength']} vs dst={dst_head['ContentLength']})."
            )

        # Step five:delete source object if move operation requested.
        if not keep_original:
            s3_client.delete_object(
                Bucket=bucket,
                Key=src_key,
            )

    @classmethod
    def move_folder(
        cls,
        s3_client: S3Client,
        bucket: str,
        src_prefix: str,
        dst_prefix: str,
        overwrite: bool = False,
        keep_original: bool = True,
    ) -> None:
        """
        Move every object under source prefix to destination prefix.

        All objects maintain their relative paths during the move operation.
        Example:'landing/' to 'process/' transforms 'landing/file.csv' into
        'process/file.csv'.

        Args:
            s3_client: Boto3 S3 client instance
            bucket: S3 bucket name
            src_prefix: Source folder prefix
            dst_prefix: Destination folder prefix
            overwrite: If False, raise error if destination exists
            keep_original: If True, keep source files after move
        """
        if not src_prefix.endswith("/"):
            src_prefix += "/"
        if not dst_prefix.endswith("/"):
            dst_prefix += "/"

        paginator = s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=bucket,
            Prefix=src_prefix,
        ):
            for obj in page.get("Contents", []):
                src_key = obj["Key"]
                suffix = src_key[len(src_prefix) :]
                dst_key = f"{dst_prefix}{suffix}"
                cls.move_file(
                    s3_client,
                    bucket=bucket,
                    src_key=src_key,
                    dst_key=dst_key,
                    overwrite=overwrite,
                    keep_original=keep_original,
                )

    @staticmethod
    def move_blob_folder(
        s3_client: S3Client,
        src_bucket: str,
        src_prefix: str,
        dst_bucket: str,
        dst_prefix: str = "",
    ) -> None:
        """
        Move blobs between buckets with prefix transformation.

        Args:
            s3_client: Boto3 S3 client instance
            src_bucket: Source bucket name
            src_prefix: Source prefix path
            dst_bucket: Destination bucket name
            dst_prefix: Destination prefix path
        """
        paginator = s3_client.get_paginator("list_objects_v2")
        transfer = S3Transfer(s3_client)

        for page in paginator.paginate(
            Bucket=src_bucket,
            Prefix=src_prefix,
        ):
            for obj in page.get("Contents", []):
                src_key = obj["Key"]
                # Build destination key by swapping the prefix root.
                suffix = src_key[len(src_prefix) :]
                dst_key = f"{dst_prefix}{suffix}"

                transfer.copy(
                    {"Bucket": src_bucket, "Key": src_key},
                    dst_bucket,
                    dst_key,
                    extra_args={"MetadataDirective": "COPY", "ACL": "private"},
                )
                s3_client.delete_object(
                    Bucket=src_bucket,
                    Key=src_key,
                )

    @classmethod
    def delete_blob_folder(
        cls,
        s3_client: S3Client,
        bucket: str,
        prefix: str,
        include_placeholder: bool = True,
        versioned: bool | None = None,
    ) -> dict[str, int]:
        """
        Delete everything under a 'folder' (prefix).

        If the bucket is versioned, deletes all versions and delete-markers too.

        :param s3_client: boto3 S3 client
        :param bucket: bucket name
        :param prefix: folder-like prefix (e.g., 'data/reports/')
        :param include_placeholder: also try to delete the zero-byte
            'folder/' object if present
        :param versioned: force behavior; if None, will auto-detect via
            get_bucket_versioning()
        :return: counts dict: {'objects': X, 'versions': Y, 'markers': Z}
        """
        if not prefix:
            raise ValueError("prefix is required")
        if not prefix.endswith("/"):
            prefix = prefix + "/"

        # Detect versioning status:enabled or suspended means versioned.
        if versioned is None:
            try:
                status = s3_client.get_bucket_versioning(
                    Bucket=bucket,
                ).get("Status")
                versioned = status in ("Enabled", "Suspended")
            except ClientError:
                # Fall back to non-versioned behavior on error.
                versioned = False

        counts = {"objects": 0, "versions": 0, "markers": 0}

        if versioned:
            # Remove all versions and delete markers under the prefix.
            paginator = s3_client.get_paginator("list_object_versions")
            for page in paginator.paginate(
                Bucket=bucket,
                Prefix=prefix,
            ):
                version_items = [
                    {"Key": v["Key"], "VersionId": v["VersionId"]}
                    for v in page.get("Versions", [])
                ]
                marker_items = [
                    {"Key": m["Key"], "VersionId": m["VersionId"]}
                    for m in page.get("DeleteMarkers", [])
                ]

                if version_items:
                    counts["versions"] += cls._batch_delete(
                        s3_client,
                        bucket=bucket,
                        objects=version_items,
                    )
                if marker_items:
                    counts["markers"] += cls._batch_delete(
                        s3_client,
                        bucket=bucket,
                        objects=marker_items,
                    )

            # Placeholder object would already be covered above.
        else:
            # Non-versioned deletion:remove plain objects under the prefix.
            paginator = s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(
                Bucket=bucket,
                Prefix=prefix,
            ):
                keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
                if keys:
                    counts["objects"] += cls._batch_delete(
                        s3_client,
                        bucket=bucket,
                        objects=keys,
                    )

            # Optionally try to delete the zero byte folder key itself.
            if include_placeholder:
                try:
                    # Deleting a non-existent key is idempotent and returns success.
                    s3_client.delete_object(
                        Bucket=bucket,
                        Key=prefix,
                    )
                    # Not incrementing counts since existence is unknown.
                except ClientError:
                    pass

        return counts
