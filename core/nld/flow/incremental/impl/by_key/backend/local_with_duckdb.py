import json
import os
from pathlib import Path
from typing import Any, Literal

from nld.connector.duckdb import DuckDBEngine
from nld.connector.local import LocalFileSystemConnector
from nld.flow.backend.local import LocalBackendMixin
from nld.flow.incremental.impl.by_key.backend.base_with_pydantic import (
    ByKeyStateBackendManager,
)
from nld.flow.incremental.impl.by_key.state import (
    ByKeyProcessingState,
    ByKeySingleKeyState,
    ByKeyState,
)
from nld.flow.incremental.models import (
    GENERAL_STATE_NAME,
    PROCESSED_STATE_NAME,
    IncrementalStateStatus,
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
    ByKeyStateBackendManager[LocalFileSystemConnector],
):
    """
    BY_KEY State Backend Manager for local filesystem using DuckDB engine.

    DuckDB provides optimized SQL queries on Parquet files without loading
    the entire dataset into memory.

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

    def read_current_state(self) -> ByKeyState:
        """Retrieve the current state using DuckDB to read Parquet."""
        file_path = str(self.general_state_file_path)

        if os.path.isfile(file_path):
            return self._read_parquet_with_duckdb(self.general_state_file_path)

        return ByKeyState(keys={})

    def _read_parquet_with_duckdb(self, file_path: Path) -> ByKeyState:
        """Read Parquet file using DuckDB and convert to ByKeyState."""
        result, columns = self.duckdb_engine.read_parquet_with_columns(file_path)

        keys: dict[str, ByKeySingleKeyState] = {}
        for row in result:
            row_dict = dict(zip(columns, row, strict=False))
            name = row_dict["name"]
            parameters_str = row_dict.get("parameters")
            parameters = json.loads(parameters_str) if parameters_str else None

            keys[name] = ByKeySingleKeyState(
                name=name,
                status=row_dict.get("status") or IncrementalStateStatus.NOT_PROCESSED,
                last_successfully_processed_at=row_dict.get(
                    "last_successfully_processed_at"
                ),
                last_processed_at=row_dict.get("last_processed_at"),
                last_process_status=(
                    row_dict.get("last_process_status")
                    or IncrementalStateStatus.NOT_PROCESSED
                ),
                last_process_error_message=row_dict.get("last_process_error_message"),
                first_processed_at=row_dict.get("first_processed_at"),
                source_deleted_at=row_dict.get("source_deleted_at"),
                parameters=parameters,
            )

        return ByKeyState(keys=keys)

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

    def _write_parquet_with_duckdb(self, state: ByKeyState) -> None:
        """Write ByKeyState to Parquet file using DuckDB."""
        import pandas as pd

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

        if records:
            df = pd.DataFrame(records)
            os.makedirs(self.general_state_file_path.parent, exist_ok=True)
            self.duckdb_engine.write_dataframe_to_parquet(
                df, self.general_state_file_path, "state_data"
            )
        else:
            import pyarrow as pa
            import pyarrow.parquet as pq

            from nld.flow.incremental.impl.by_key.schema import get_by_key_state_schema

            os.makedirs(self.general_state_file_path.parent, exist_ok=True)
            empty_table = pa.Table.from_pylist([], schema=get_by_key_state_schema())
            pq.write_table(empty_table, self.general_state_file_path)

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
