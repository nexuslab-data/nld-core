import json
from pathlib import Path
from typing import Any, Literal

import pyarrow as pa
import pyarrow.parquet as pq

from nld.connector.s3_blob_storage import S3ObjectStorageConnector
from nld.flow.backend.s3_blob_storage import S3BackendMixin
from nld.flow.incremental.impl.by_key.backend.s3_blob_storage_base import (
    S3ByKeyBackendStateManagerBase,
)
from nld.flow.incremental.impl.by_key.schema import get_by_key_state_schema
from nld.flow.incremental.impl.by_key.state import (
    ByKeyProcessingState,
    ByKeySingleKeyState,
    ByKeyState,
)
from nld.flow.incremental.models import (
    GENERAL_STATE_NAME,
    PROCESSED_STATE_NAME,
)
from nld.flow.incremental.models.events import (
    IncrementalBackendEngineInitialized,
)
from nld.parameters import ExecutionParameterDefinition

# JSON file names
PROCESSED_STATE_FILE_NAME = f"{PROCESSED_STATE_NAME}.json"
GENERAL_STATE_FILE_NAME = f"{GENERAL_STATE_NAME}.json"

# Parquet file names
PROCESSED_STATE_PARQUET_NAME = f"{PROCESSED_STATE_NAME}.parquet"
GENERAL_STATE_PARQUET_NAME = f"{GENERAL_STATE_NAME}.parquet"

# File format type
FileFormat = Literal["json", "parquet"]


class S3ByKeyPydanticStateBackendManager(S3ByKeyBackendStateManagerBase):
    """
    BY_KEY State Backend Manager using Pydantic/PyArrow.

    Supports both JSON and Parquet formats.
    """

    param_definitions = [
        *S3BackendMixin.s3_param_definitions,
        ExecutionParameterDefinition(name="s3_root_path", mandatory=True),
        ExecutionParameterDefinition(
            name="file_format",
            mandatory=False,
            default_value="json",
            allowed_values=["json", "parquet"],
            help_text="Storage format: 'json' or 'parquet'",
        ),
    ]

    def __init__(
        self,
        backend_connector: S3ObjectStorageConnector,
        flow_namespace: str,
        flow_name: str,
        parameters: dict[str, Any],
        **kwargs: Any,
    ):
        super().__init__(
            backend_connector=backend_connector,
            flow_namespace=flow_namespace,
            flow_name=flow_name,
            parameters=parameters,
            **kwargs,
        )
        self.log_event(
            IncrementalBackendEngineInitialized(
                backend_type=backend_connector.connection_wrapper.type,
                engine="pydantic",
                manager_class=type(self).__name__,
            ),
        )

    @property
    def file_format(self) -> str:
        """Get the storage format (json or parquet)."""
        return self.parameters["file_format"]  # type: ignore[no-any-return]

    @property
    def file_extension(self) -> str:
        """Get the file extension based on the file format."""
        return "parquet" if self.file_format == "parquet" else "json"

    # Incremental State methods
    @property
    def general_state_file_name(self) -> str:
        """Get the general state file name based on file_format."""
        return f"{GENERAL_STATE_NAME}.{self.file_extension}"

    @property
    def processed_state_file_name(self) -> str:
        """Get the processed state file name based on file_format."""
        return f"{PROCESSED_STATE_NAME}.{self.file_extension}"

    @property
    def local_processed_state_file_path(self) -> Path:
        return Path(self.local_state_dir / self.processed_state_file_name)

    @property
    def local_post_processing_state_file_path(self) -> Path:
        return Path(self.local_state_dir / self.general_state_file_name)

    def read_current_state(self) -> ByKeyState:
        """
        Retrieve the current state based on file_format.

        Returns:
            The key flow state.
        """
        if self.file_format == "parquet":
            return self._read_by_key_state_from_parquet()
        return self._read_from_json()

    def _read_from_json(self) -> ByKeyState:
        """Read state from JSON file."""
        key_flow_state_storage_path = (
            f"{self.backend_state_root_path}/{self.general_state_file_name}"
        )

        if self.backend_connector.check_if_file_exists(
            obj_storage_path=key_flow_state_storage_path
        ):
            self.backend_connector.download_file_to_local_path(
                obj_storage_path=key_flow_state_storage_path,
                local_file_path=str(self.local_post_processing_state_file_path),
            )
            return ByKeyState.read_json_file(self.local_post_processing_state_file_path)

        # First run - create an empty key state
        return ByKeyState(keys={})

    def _read_by_key_state_from_parquet(self) -> ByKeyState:
        """Read state from Parquet file."""
        key_flow_state_storage_path = (
            f"{self.backend_state_root_path}/{self.general_state_file_name}"
        )

        if self.backend_connector.check_if_file_exists(
            obj_storage_path=key_flow_state_storage_path
        ):
            self.backend_connector.download_file_to_local_path(
                obj_storage_path=key_flow_state_storage_path,
                local_file_path=str(self.local_post_processing_state_file_path),
            )
            return self._parquet_to_by_key_state(
                self.local_post_processing_state_file_path
            )

        # First run - create an empty key state
        return ByKeyState(keys={})

    def _parquet_to_by_key_state(self, file_path: Path) -> ByKeyState:
        """Convert Parquet file to ByKeyState."""
        table = pq.read_table(file_path)
        keys: dict[str, ByKeySingleKeyState] = {}

        for batch in table.to_batches():
            for row_idx in range(batch.num_rows):
                name = batch.column("name")[row_idx].as_py()
                parameters_str = batch.column("parameters")[row_idx].as_py()
                parameters = json.loads(parameters_str) if parameters_str else None

                keys[name] = ByKeySingleKeyState(
                    name=name,
                    status=batch.column("status")[row_idx].as_py(),
                    last_successfully_processed_at=batch.column(
                        "last_successfully_processed_at"
                    )[row_idx].as_py(),
                    last_processed_at=batch.column("last_processed_at")[
                        row_idx
                    ].as_py(),
                    last_process_status=batch.column("last_process_status")[
                        row_idx
                    ].as_py(),
                    last_process_error_message=batch.column(
                        "last_process_error_message"
                    )[row_idx].as_py(),
                    first_processed_at=batch.column("first_processed_at")[
                        row_idx
                    ].as_py(),
                    source_deleted_at=batch.column("source_deleted_at")[
                        row_idx
                    ].as_py(),
                    parameters=parameters,
                )

        return ByKeyState(keys=keys)

    def write_processing_state(
        self,
        processing_flow_state: ByKeyProcessingState,
    ) -> None:
        """Persist the run's processing state as one file under ``state/<ts>/``."""
        self._write_processing_state_single_file(
            processing_flow_state=processing_flow_state,
            serialize=self._serialize_processing_state,
        )

    def _serialize_processing_state(
        self,
        processing_flow_state: ByKeyProcessingState,
        local_path: Path,
    ) -> None:
        """Serialise the processing state in the configured ``file_format``."""
        if self.file_format == "parquet":
            self._write_by_key_processing_state_to_parquet(
                state=processing_flow_state,
                local_path=local_path,
            )
        else:
            processing_flow_state.write_json_file(
                file_path=local_path,
            )

    def write_post_processing_state(
        self, post_processing_flow_state: ByKeyState
    ) -> None:
        """Write post-processing state based on file_format."""
        self._create_local_state_dir()
        if self.file_format == "parquet":
            self._write_to_parquet(post_processing_flow_state)
        else:
            self._write_to_json(post_processing_flow_state)

    def _write_to_json(self, state: ByKeyState) -> None:
        """Write state to JSON file."""
        state.write_json_file(file_path=self.local_post_processing_state_file_path)
        self._upload_file_to_state_at_root_folder(
            [self.local_post_processing_state_file_path]
        )

    def _write_to_parquet(self, state: ByKeyState) -> None:
        """Write state to Parquet file."""
        table = self._convert_by_key_state_to_parquet(state)
        pq.write_table(table, self.local_post_processing_state_file_path)

        # Upload to backend
        self._upload_file_to_state_at_root_folder(
            [self.local_post_processing_state_file_path]
        )

    def _convert_by_key_state_to_parquet(self, state: ByKeyState) -> pa.Table:
        """Convert ByKeyState to PyArrow Table."""
        records = [
            {
                "name": ks.name,
                "status": ks.status,
                "last_successfully_processed_at": (ks.last_successfully_processed_at),
                "last_processed_at": ks.last_processed_at,
                "last_process_status": ks.last_process_status,
                "last_process_error_message": ks.last_process_error_message,
                "first_processed_at": ks.first_processed_at,
                "source_deleted_at": ks.source_deleted_at,
                "parameters": json.dumps(ks.parameters) if ks.parameters else None,
            }
            for ks in state.keys.values()
        ]

        return pa.Table.from_pylist(records, schema=get_by_key_state_schema())
