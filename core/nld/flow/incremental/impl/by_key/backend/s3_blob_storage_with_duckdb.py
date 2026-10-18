from pathlib import Path
from typing import Any, Literal

from nld.connector.duckdb import DuckDBEngine
from nld.connector.s3_blob_storage import S3ObjectStorageConnector
from nld.flow.backend.s3_blob_storage import S3BackendMixin
from nld.flow.incremental.impl.by_key import (
    ByKeyProcessingState,
    ByKeyState,
)
from nld.flow.incremental.impl.by_key.backend.base_with_duckdb import (
    ByKeyDuckDBKeyStateMixin,
)
from nld.flow.incremental.impl.by_key.backend.s3_blob_storage_base import (
    S3ByKeyBackendStateManagerBase,
)
from nld.flow.incremental.impl.by_key.constants import (
    GENERAL_STATE_NAME,
    PROCESSED_STATE_NAME,
)
from nld.flow.incremental.models.events import (
    IncrementalBackendEngineInitialized,
)
from nld.parameters import ExecutionParameterDefinition

# Parquet file names
PROCESSED_STATE_PARQUET_NAME = f"{PROCESSED_STATE_NAME}.parquet"
GENERAL_STATE_PARQUET_NAME = f"{GENERAL_STATE_NAME}.parquet"

# File format type (DuckDB only supports parquet)
FileFormat = Literal["parquet"]


class S3ByKeyDuckDBStateBackendManager(
    ByKeyDuckDBKeyStateMixin,
    S3ByKeyBackendStateManagerBase,
):
    """
    BY_KEY State Backend Manager using DuckDB engine.

    DuckDB provides optimized SQL queries on Parquet files without loading
    the entire dataset into memory. A run downloads the key state once and
    merges the keys it processed into it (see ``ByKeyDuckDBKeyStateMixin``).

    Note: This backend only supports parquet format. Using JSON will raise an error.
    """

    param_definitions = [
        *S3BackendMixin.s3_param_definitions,
        ExecutionParameterDefinition(name="s3_root_path", mandatory=True),
        ExecutionParameterDefinition(
            name="file_format",
            mandatory=False,
            default_value="parquet",
            help_text="Storage format: only 'parquet' is supported with DuckDB engine",
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

        # Validate file_format
        if self.file_format != "parquet":
            msg = (
                f"DuckDB engine requires file_format='parquet', "
                f"got '{self.file_format}'"
            )
            raise ValueError(msg)

        # DuckDB engine for SQL operations
        self._duckdb_engine: DuckDBEngine | None = None
        self._is_key_state_prepared = False
        self._prepared_key_state_file_path: Path | None = None

        self.log_event(
            IncrementalBackendEngineInitialized(
                backend_type=backend_connector.connection_wrapper.type,
                engine="duckdb",
                manager_class=type(self).__name__,
            ),
        )

    @property
    def duckdb_engine(self) -> DuckDBEngine:
        """Lazy-loaded DuckDB engine."""
        if self._duckdb_engine is None:
            self._duckdb_engine = DuckDBEngine()
        return self._duckdb_engine

    def close(self) -> None:
        """Close the DuckDB engine if it exists."""
        if self._duckdb_engine is not None:
            self._duckdb_engine.close()
            self._duckdb_engine = None

    @property
    def file_format(self) -> FileFormat:
        """Get the storage format (only parquet for DuckDB)."""
        return self.parameters["file_format"]  # type: ignore[no-any-return]

    @property
    def local_processed_state_file_path(self) -> Path:
        return Path(self.local_state_dir / PROCESSED_STATE_PARQUET_NAME)

    @property
    def local_post_processing_state_file_path(self) -> Path:
        return Path(self.local_state_dir / GENERAL_STATE_PARQUET_NAME)

    @property
    def key_state_file_path(self) -> Path:
        """The local copy of the key state, uploaded after each write."""
        return self.local_post_processing_state_file_path

    def prepare_current_state(self) -> None:
        """Download the stored key state once for the queries of this run."""
        self._create_local_state_dir()
        key_flow_state_storage_path = (
            f"{self.backend_state_root_path}/{GENERAL_STATE_PARQUET_NAME}"
        )
        self._prepared_key_state_file_path = None
        if self.backend_connector.check_if_file_exists(
            obj_storage_path=key_flow_state_storage_path,
        ):
            self.backend_connector.download_file_to_local_path(
                obj_storage_path=key_flow_state_storage_path,
                local_file_path=str(self.key_state_file_path),
            )
            self._prepared_key_state_file_path = self.key_state_file_path
        self._is_key_state_prepared = True

    def _current_key_state_file_path(self) -> Path | None:
        """Return the downloaded key state, or None before the first run."""
        if not self._is_key_state_prepared:
            self.prepare_current_state()
        return self._prepared_key_state_file_path

    def _publish_key_state_file(self) -> None:
        """Upload the merged key state as the stored key state."""
        self._upload_file_to_state_at_root_folder([self.key_state_file_path])
        self._prepared_key_state_file_path = self.key_state_file_path

    def read_current_state(self) -> ByKeyState:
        """
        Retrieve the current state using DuckDB to read Parquet.

        Returns:
            The key flow state.
        """
        key_flow_state_storage_path = (
            f"{self.backend_state_root_path}/{GENERAL_STATE_PARQUET_NAME}"
        )
        key_flow_state_file_path = self.local_state_dir / GENERAL_STATE_PARQUET_NAME

        if self.backend_connector.check_if_file_exists(
            obj_storage_path=key_flow_state_storage_path
        ):
            self.backend_connector.download_file_to_local_path(
                obj_storage_path=key_flow_state_storage_path,
                local_file_path=str(key_flow_state_file_path),
            )
            return self._read_parquet_with_duckdb(key_flow_state_file_path)

        # First run - create an empty key state
        return ByKeyState(keys={})

    def write_processing_state(
        self,
        processing_flow_state: ByKeyProcessingState,
    ) -> None:
        """Write the run's processing state as one parquet under ``state/<ts>/``."""
        self._write_processing_state_single_file(
            processing_flow_state=processing_flow_state,
            serialize=self._serialize_processing_state,
        )

    def _serialize_processing_state(
        self,
        processing_flow_state: ByKeyProcessingState,
        local_path: Path,
    ) -> None:
        """Serialise the processing state to a parquet file."""
        self._write_by_key_processing_state_to_parquet(
            state=processing_flow_state,
            local_path=local_path,
        )

    def write_post_processing_state(
        self, post_processing_flow_state: ByKeyState
    ) -> None:
        """Write post-processing state using DuckDB to write Parquet."""
        self._create_local_state_dir()
        self._write_parquet_with_duckdb(post_processing_flow_state)
        self._upload_file_to_state_at_root_folder(
            [self.local_post_processing_state_file_path]
        )

    # DuckDB-specific optimized methods
    def get_state_summary(self) -> dict[str, int]:
        """
        Get summary statistics via DuckDB SQL query (no full load).

        Returns:
            Dictionary with 'total' and 'succeeded' counts.
        """
        key_flow_state_storage_path = (
            f"{self.backend_state_root_path}/{GENERAL_STATE_PARQUET_NAME}"
        )
        key_flow_state_file_path = self.local_state_dir / GENERAL_STATE_PARQUET_NAME

        if not self.backend_connector.check_if_file_exists(
            obj_storage_path=key_flow_state_storage_path
        ):
            return {"total": 0, "succeeded": 0}

        self.backend_connector.download_file_to_local_path(
            obj_storage_path=key_flow_state_storage_path,
            local_file_path=str(key_flow_state_file_path),
        )

        agg_query = (
            "COUNT(*) as total, "
            "SUM(CASE WHEN status = 'SUCCEEDED' THEN 1 ELSE 0 END) as succeeded"
        )
        result = self.duckdb_engine.execute_aggregate_query(
            key_flow_state_file_path,
            agg_query,
        )
        if result:
            return {"total": result[0], "succeeded": result[1] or 0}
        return {"total": 0, "succeeded": 0}

    def retrieve_keys_by_status(self, statuses: list[str]) -> list[str]:
        """
        Retrieve key names filtered by status using DuckDB query.

        Args:
            statuses: List of status values to filter by.

        Returns:
            List of key names matching the statuses.
        """
        key_flow_state_storage_path = (
            f"{self.backend_state_root_path}/{GENERAL_STATE_PARQUET_NAME}"
        )
        key_flow_state_file_path = self.local_state_dir / GENERAL_STATE_PARQUET_NAME

        if not self.backend_connector.check_if_file_exists(
            obj_storage_path=key_flow_state_storage_path
        ):
            return []

        self.backend_connector.download_file_to_local_path(
            obj_storage_path=key_flow_state_storage_path,
            local_file_path=str(key_flow_state_file_path),
        )

        status_list = ", ".join(f"'{s}'" for s in statuses)
        result = self.duckdb_engine.execute_filter_query(
            key_flow_state_file_path,
            "name",
            f"status IN ({status_list})",
        )
        return [row[0] for row in result]

    def supports_optimized_queries(self) -> bool:
        """Indicate that this backend supports optimized DuckDB queries."""
        return True
