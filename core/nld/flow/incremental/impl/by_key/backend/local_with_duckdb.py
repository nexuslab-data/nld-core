import os
from pathlib import Path
from typing import Any, Literal

from nld.connector.duckdb import DuckDBEngine
from nld.connector.local import LocalFileSystemConnector
from nld.flow.backend.local import LocalBackendMixin
from nld.flow.incremental.impl.by_key.backend.base_with_duckdb import (
    ByKeyDuckDBKeyStateMixin,
)
from nld.flow.incremental.impl.by_key.backend.base_with_pydantic import (
    ByKeyStateBackendManager,
)
from nld.flow.incremental.impl.by_key.constants import (
    GENERAL_STATE_NAME,
    PROCESSED_STATE_NAME,
)
from nld.flow.incremental.impl.by_key.state import (
    ByKeyProcessingState,
    ByKeyState,
)
from nld.flow.incremental.models.events import (
    IncrementalBackendEngineInitialized,
)
from nld.parameters import ExecutionParameterDefinition

PROCESSED_STATE_PARQUET_NAME = f"{PROCESSED_STATE_NAME}.parquet"
GENERAL_STATE_PARQUET_NAME = f"{GENERAL_STATE_NAME}.parquet"

FileFormat = Literal["parquet"]


class LocalByKeyDuckDBStateBackendManager(
    LocalBackendMixin,
    ByKeyDuckDBKeyStateMixin,
    ByKeyStateBackendManager[LocalFileSystemConnector],
):
    """
    BY_KEY State Backend Manager for local filesystem using DuckDB engine.

    DuckDB provides optimized SQL queries on Parquet files without loading
    the entire dataset into memory. A run merges the keys it processed into
    the key state file (see ``ByKeyDuckDBKeyStateMixin``).

    Note: This backend only supports parquet format. Using JSON will raise an error.
    """

    param_definitions = [
        ExecutionParameterDefinition(
            name="backend_root_path",
            mandatory=True,
        ),
        ExecutionParameterDefinition(
            name="file_format",
            mandatory=False,
            default_value="parquet",
            help_text="Storage format: only 'parquet' is supported with DuckDB engine",
        ),
    ]

    def __init__(
        self,
        backend_connector: LocalFileSystemConnector,
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

        if self.file_format != "parquet":
            msg = (
                f"DuckDB engine requires file_format='parquet', "
                f"got '{self.file_format}'"
            )
            raise ValueError(msg)

        self._duckdb_engine: DuckDBEngine | None = None

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
    def general_state_file_path(self) -> Path:
        return Path(
            os.path.join(
                self.backend_state_root_path,
                GENERAL_STATE_PARQUET_NAME,
            )
        )

    @property
    def processed_state_file_path(self) -> Path:
        return Path(
            os.path.join(
                self.backend_state_for_processing_path,
                PROCESSED_STATE_PARQUET_NAME,
            )
        )

    @property
    def key_state_file_path(self) -> Path:
        """The key state file, written in place."""
        return self.general_state_file_path

    def prepare_current_state(self) -> None:
        """Nothing to prepare: the key state file is already local."""

    def _current_key_state_file_path(self) -> Path | None:
        """Return the key state file, or None before the first run."""
        if os.path.isfile(self.general_state_file_path):
            return self.general_state_file_path
        return None

    def _publish_key_state_file(self) -> None:
        """Nothing to publish: the merge wrote the key state file in place."""

    def read_current_state(self) -> ByKeyState:
        """Retrieve the current state using DuckDB to read Parquet."""
        file_path = str(self.general_state_file_path)

        if os.path.isfile(file_path):
            return self._read_parquet_with_duckdb(self.general_state_file_path)

        return ByKeyState(keys={})

    def write_processing_state(
        self,
        processing_flow_state: ByKeyProcessingState,
    ) -> None:
        """Write processed state as JSON to the processing folder."""
        os.makedirs(self.processed_state_file_path.parent, exist_ok=True)
        processing_flow_state.write_json_file(file_path=self.processed_state_file_path)

    def write_post_processing_state(
        self, post_processing_flow_state: ByKeyState
    ) -> None:
        """Write post-processing state using DuckDB to write Parquet."""
        self._write_parquet_with_duckdb(post_processing_flow_state)

    def get_state_summary(self) -> dict[str, int]:
        """Get summary statistics via DuckDB SQL query (no full load)."""
        file_path = str(self.general_state_file_path)

        if not os.path.isfile(file_path):
            return {"total": 0, "succeeded": 0}

        agg_query = (
            "COUNT(*) as total, "
            "SUM(CASE WHEN status = 'SUCCEEDED' THEN 1 ELSE 0 END) as succeeded"
        )
        result = self.duckdb_engine.execute_aggregate_query(
            self.general_state_file_path,
            agg_query,
        )
        if result:
            return {"total": result[0], "succeeded": result[1] or 0}
        return {"total": 0, "succeeded": 0}

    def retrieve_keys_by_status(self, statuses: list[str]) -> list[str]:
        """Retrieve key names filtered by status using DuckDB query."""
        file_path = str(self.general_state_file_path)

        if not os.path.isfile(file_path):
            return []

        status_list = ", ".join(f"'{s}'" for s in statuses)
        result = self.duckdb_engine.execute_filter_query(
            self.general_state_file_path,
            "name",
            f"status IN ({status_list})",
        )
        return [row[0] for row in result]

    def supports_optimized_queries(self) -> bool:
        """Indicate that this backend supports optimized DuckDB queries."""
        return True
