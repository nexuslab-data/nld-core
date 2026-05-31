from __future__ import annotations

from nld.flow.execution.backend.s3_blob_storage_with_pydantic import (
    S3ExecutionPydanticBackendStateManager,
)


class ExecutionS3BlobStorageToParquetMigration:
    """
    Migration utility for Execution state between JSON and Parquet formats.

    Uses composition to access backend manager methods.

    Example usage:
        backend = S3ExecutionPydanticBackendStateManager(
            backend_connector=connector,
            parameters={"s3_root_path": "...", "file_format": "json"},
            ...
        )
        migration = ExecutionS3BlobStorageMigration(backend)
        if migration.check_migration_needed():
            migration.migrate_to_parquet()
    """

    def __init__(self, backend_manager: S3ExecutionPydanticBackendStateManager) -> None:
        if backend_manager.file_format == "parquet":
            raise ValueError(
                "Migration to Parquet format is not supported from parquet backend."
            )
        self._backend = backend_manager

    def check_json_exists(self) -> bool:
        """Check if JSON state files exist on backend."""
        from nld.flow.execution.utils import (
            EXECUTION_HISTORY_NAME,
            EXECUTION_STATE_NAME,
        )

        state_path = (
            f"{self._backend.backend_state_root_path}/{EXECUTION_STATE_NAME}.json"
        )
        history_path = (
            f"{self._backend.backend_state_root_path}/{EXECUTION_HISTORY_NAME}.json"
        )

        return self._backend.backend_connector.check_if_file_exists(
            obj_storage_path=state_path
        ) and self._backend.backend_connector.check_if_file_exists(
            obj_storage_path=history_path
        )

    def check_parquet_exists(self) -> bool:
        """Check if Parquet state files exist on backend."""
        from nld.flow.execution.utils import (
            EXECUTION_HISTORY_NAME,
            EXECUTION_STATE_NAME,
        )

        state_path = (
            f"{self._backend.backend_state_root_path}/{EXECUTION_STATE_NAME}.parquet"
        )
        history_path = (
            f"{self._backend.backend_state_root_path}/{EXECUTION_HISTORY_NAME}.parquet"
        )

        return self._backend.backend_connector.check_if_file_exists(
            obj_storage_path=state_path
        ) and self._backend.backend_connector.check_if_file_exists(
            obj_storage_path=history_path
        )

    def check_migration_needed(self) -> bool:
        """Check if migration from JSON to Parquet is needed."""
        return self.check_json_exists() and not self.check_parquet_exists()

    def migrate_to_parquet(self, archive_json: bool = True) -> None:
        """
        Migrate existing JSON state to Parquet format.

        Call this BEFORE changing file_format to 'parquet' in config.

        Args:
            archive_json: If True, rename .json files to .json.archived on backend.
        """
        # Read current state from JSON
        execution_state, execution_history = (
            self._backend.retrieve_latest_execution_state()
        )

        # Write to Parquet (need to extract execution_info from state)
        if execution_state.last_processed:
            self._backend._write_execution_info_to_parquet(
                current_execution_info=execution_state.last_processed,
            )
            self._backend._write_execution_history_to_parquet(
                execution_history=execution_history,
            )
            self._backend._write_execution_state_to_parquet(
                current_execution_info=execution_state.last_processed,
            )

        # Archive JSON if requested
        if archive_json:
            self._archive_json_files()

    def _archive_json_files(self) -> None:
        """Rename JSON files to .json.archived on backend (move operation)."""
        from nld.connector.s3_blob_storage.s3_object_storage_utils import (
            S3ObjectStorageUtils,
        )
        from nld.flow.execution.utils import (
            EXECUTION_HISTORY_NAME,
            EXECUTION_STATE_NAME,
        )

        s3_client = self._backend.backend_connector.connection_wrapper.connection
        if s3_client is None:
            msg = "S3 client connection is not available"
            raise RuntimeError(msg)

        bucket = (
            self._backend.backend_connector.connection_wrapper.credentials.bucket_name
        )

        # Archive state file
        root = self._backend.backend_state_root_path
        execution_state_json = f"{EXECUTION_STATE_NAME}.json"
        state_source = f"{root}/{execution_state_json}"
        state_archive = f"{root}/{execution_state_json}.archived"
        S3ObjectStorageUtils.move_file(
            s3_client=s3_client,
            bucket=bucket,
            src_key=state_source,
            dst_key=state_archive,
            keep_original=False,
        )

        # Archive history file
        execution_history_json = f"{EXECUTION_HISTORY_NAME}.json"
        history_source = f"{root}/{execution_history_json}"
        history_archive = f"{root}/{execution_history_json}.archived"
        S3ObjectStorageUtils.move_file(
            s3_client=s3_client,
            bucket=bucket,
            src_key=history_source,
            dst_key=history_archive,
            keep_original=False,
        )

    def rollback_to_json(self) -> None:
        """
        Rollback from Parquet to JSON format.

        Restores JSON from archive and removes Parquet files.
        """
        from nld.connector.s3_blob_storage.s3_object_storage_utils import (
            S3ObjectStorageUtils,
        )
        from nld.flow.execution.utils import (
            EXECUTION_HISTORY_NAME,
            EXECUTION_STATE_NAME,
        )

        s3_client = self._backend.backend_connector.connection_wrapper.connection
        if s3_client is None:
            msg = "S3 client connection is not available"
            raise RuntimeError(msg)

        bucket = (
            self._backend.backend_connector.connection_wrapper.credentials.bucket_name
        )

        # Restore state file
        root = self._backend.backend_state_root_path
        execution_state_json = f"{EXECUTION_STATE_NAME}.json"
        execution_state_parquet = f"{EXECUTION_STATE_NAME}.parquet"
        state_archive = f"{root}/{execution_state_json}.archived"
        state_json = f"{root}/{execution_state_json}"
        state_parquet = f"{root}/{execution_state_parquet}"

        if not self._backend.backend_connector.check_if_file_exists(
            obj_storage_path=state_archive
        ):
            msg = "No archived JSON state file found for rollback"
            raise FileNotFoundError(msg)

        S3ObjectStorageUtils.move_file(
            s3_client=s3_client,
            bucket=bucket,
            src_key=state_archive,
            dst_key=state_json,
            keep_original=False,
        )

        if self._backend.backend_connector.check_if_file_exists(
            obj_storage_path=state_parquet
        ):
            s3_client.delete_object(Bucket=bucket, Key=state_parquet)

        # Restore history file
        execution_history_json = f"{EXECUTION_HISTORY_NAME}.json"
        execution_history_parquet = f"{EXECUTION_HISTORY_NAME}.parquet"
        history_archive = f"{root}/{execution_history_json}.archived"
        history_json = f"{root}/{execution_history_json}"
        history_parquet = f"{root}/{execution_history_parquet}"

        if not self._backend.backend_connector.check_if_file_exists(
            obj_storage_path=history_archive
        ):
            msg = "No archived JSON history file found for rollback"
            raise FileNotFoundError(msg)

        S3ObjectStorageUtils.move_file(
            s3_client=s3_client,
            bucket=bucket,
            src_key=history_archive,
            dst_key=history_json,
            keep_original=False,
        )

        if self._backend.backend_connector.check_if_file_exists(
            obj_storage_path=history_parquet
        ):
            s3_client.delete_object(Bucket=bucket, Key=history_parquet)
