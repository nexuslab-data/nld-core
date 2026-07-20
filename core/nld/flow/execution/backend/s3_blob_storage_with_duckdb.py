import json
from pathlib import Path
from typing import Any, Literal

from nld.connector.duckdb import DuckDBEngine
from nld.connector.s3_blob_storage import S3ObjectStorageConnector
from nld.flow.backend.s3_blob_storage import S3BackendMixin
from nld.flow.execution import (
    FlowExecutionHistory,
    FlowExecutionInfo,
    FlowExecutionState,
)
from nld.flow.execution.backend.s3_blob_storage_base import (
    S3ExecutionBackendStateManagerBase,
)
from nld.flow.execution.events import ExecutionBackendEngineInitialized
from nld.flow.execution.utils import (
    EXECUTION_HISTORY_NAME,
    EXECUTION_INFO_NAME,
    EXECUTION_STATE_NAME,
)
from nld.parameters import ExecutionParameterDefinition

# File format type (DuckDB only supports parquet)
FileFormat = Literal["parquet"]


class S3ExecutionDuckDBBackendStateManager(S3ExecutionBackendStateManagerBase):
    """
    Execution Backend State Manager using DuckDB engine.

    DuckDB provides optimized SQL queries on Parquet files without loading
    the entire dataset into memory.

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

        self.log_event(
            ExecutionBackendEngineInitialized(
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
    def file_extension(self) -> str:
        """Get the file extension (always parquet for DuckDB)."""
        return "parquet"

    @property
    def execution_info_file_name(self) -> str:
        """Get the execution info file name based on file_format."""
        return f"{EXECUTION_INFO_NAME}.{self.file_extension}"

    @property
    def execution_state_file_name(self) -> str:
        """Get the execution state file name based on file_format."""
        return f"{EXECUTION_STATE_NAME}.{self.file_extension}"

    @property
    def execution_history_file_name(self) -> str:
        """Get the execution history file name based on file_format."""
        return f"{EXECUTION_HISTORY_NAME}.{self.file_extension}"

    @property
    def local_execution_info_file_path(self) -> Path:
        return Path(self.local_state_dir / self.execution_info_file_name)

    @property
    def local_execution_state_file_path(self) -> Path:
        return Path(self.local_state_dir / self.execution_state_file_name)

    @property
    def local_execution_history_file_path(self) -> Path:
        return Path(self.local_state_dir / self.execution_history_file_name)

    def retrieve_latest_execution_state(
        self,
    ) -> tuple[FlowExecutionState, FlowExecutionHistory]:
        """
        Download the latest execution state using DuckDB to read Parquet.

        Returns:
            Tuple of (FlowExecutionState, FlowExecutionHistory).
        """
        execution_state_storage_path = (
            f"{self.backend_state_root_path}/{self.execution_state_file_name}"
        )
        execution_state_file_path = (
            self.local_state_dir / self.execution_state_file_name
        )
        execution_history_storage_path = (
            f"{self.backend_state_root_path}/{self.execution_history_file_name}"
        )
        execution_history_file_path = (
            self.local_state_dir / self.execution_history_file_name
        )

        if self.backend_connector.check_if_file_exists(
            obj_storage_path=execution_state_storage_path
        ) and self.backend_connector.check_if_file_exists(
            obj_storage_path=execution_history_storage_path
        ):
            # Download and read state
            self.backend_connector.download_file_to_local_path(
                obj_storage_path=execution_state_storage_path,
                local_file_path=str(execution_state_file_path),
            )
            execution_state = self._read_execution_state_with_duckdb(
                execution_state_file_path
            )

            # Download and read history
            self.backend_connector.download_file_to_local_path(
                obj_storage_path=execution_history_storage_path,
                local_file_path=str(execution_history_file_path),
            )
            execution_history = self._read_execution_history_with_duckdb(
                execution_history_file_path
            )
        else:
            # First run
            execution_state = FlowExecutionState()
            execution_history = FlowExecutionHistory(executions=[])

        return execution_state, execution_history

    def _duckdb_row_to_execution_info(
        self, row_dict: dict[str, Any]
    ) -> FlowExecutionInfo:
        """Convert a DuckDB row dict to FlowExecutionInfo."""
        steps_str = row_dict.get("steps")
        steps = json.loads(steps_str) if steps_str else None

        return FlowExecutionInfo(
            flow_uid=row_dict["flow_uid"],
            flow_namespace=row_dict["flow_namespace"],
            flow_name=row_dict["flow_name"],
            flow_instance_name=row_dict["flow_instance_name"],
            requestor=row_dict["requestor"],
            data_load_strategy=row_dict["data_load_strategy"],
            started_at=row_dict.get("started_at"),
            ended_at=row_dict.get("ended_at"),
            execution_status=row_dict.get("execution_status"),
            execution_error=row_dict.get("execution_error"),
            pull_from=row_dict.get("pull_from"),
            pull_to=row_dict.get("pull_to"),
            previous_layer_last_updated_at=row_dict.get(
                "previous_layer_last_updated_at"
            ),
            source_extracted_at=row_dict.get("source_extracted_at"),
            source_last_updated_at=row_dict.get("source_last_updated_at"),
            steps=steps,
        )

    def _read_execution_state_with_duckdb(self, file_path: Path) -> FlowExecutionState:
        """Read Parquet file using DuckDB and convert to FlowExecutionState."""
        result, columns = self.duckdb_engine.read_parquet_with_columns(file_path)

        if not result:
            return FlowExecutionState()

        row_dict = dict(zip(columns, result[0], strict=False))
        last_processed = self._duckdb_row_to_execution_info(row_dict)
        return FlowExecutionState(last_processed=last_processed)

    def _read_execution_history_with_duckdb(
        self, file_path: Path
    ) -> FlowExecutionHistory:
        """Read Parquet file using DuckDB and convert to FlowExecutionHistory."""
        result, columns = self.duckdb_engine.read_parquet_with_columns(file_path)

        executions: list[FlowExecutionInfo] = []
        for row in result:
            row_dict = dict(zip(columns, row, strict=False))
            executions.append(self._duckdb_row_to_execution_info(row_dict))

        return FlowExecutionHistory(executions=executions)

    def save_execution_info(
        self,
        current_execution_info: FlowExecutionInfo,
        saved_step_names: list[str] | None = None,
    ) -> None:
        """Save the per-execution info Parquet file on S3 using DuckDB."""
        self._create_local_state_dir()
        self._write_execution_info_with_duckdb(
            current_execution_info,
            self.local_execution_info_file_path,
        )
        self._upload_file_to_run_state_folder(self.local_execution_info_file_path)

    def save_execution_history_complete(
        self,
        execution_history: FlowExecutionHistory,
    ) -> None:
        """Rewrite the consolidated execution history Parquet file on S3."""
        self._create_local_state_dir()
        self._write_execution_history_with_duckdb(
            execution_history,
            self.local_execution_history_file_path,
        )
        self._upload_file_to_state_at_root_folder(
            [self.local_execution_history_file_path]
        )

    def save_execution_state(
        self,
        current_execution_info: FlowExecutionInfo | None = None,
        new_execution_state: FlowExecutionState | None = None,
    ) -> None:
        """Save the execution state record using DuckDB to write Parquet on S3."""
        state_info = current_execution_info
        if (
            new_execution_state is not None
            and new_execution_state.last_processed is not None
        ):
            state_info = new_execution_state.last_processed
        assert state_info is not None
        self._create_local_state_dir()
        self._write_execution_info_with_duckdb(
            state_info,
            self.local_execution_state_file_path,
        )
        self._upload_file_to_state_at_root_folder(
            [self.local_execution_state_file_path]
        )

    def _execution_info_to_record(self, info: FlowExecutionInfo) -> dict[str, Any]:
        """Convert FlowExecutionInfo to a dict for DuckDB."""
        steps_json = None
        if info.steps:
            steps_json = json.dumps(
                [step.model_dump(mode="json") for step in info.steps]
            )

        return {
            "flow_uid": info.flow_uid,
            "flow_namespace": info.flow_namespace,
            "flow_name": info.flow_name,
            "flow_instance_name": info.flow_instance_name,
            "requestor": info.requestor,
            "data_load_strategy": info.data_load_strategy,
            "started_at": info.started_at,
            "ended_at": info.ended_at,
            "execution_status": info.execution_status,
            "execution_error": info.execution_error,
            "pull_from": info.pull_from,
            "pull_to": info.pull_to,
            "previous_layer_last_updated_at": info.previous_layer_last_updated_at,
            "source_extracted_at": info.source_extracted_at,
            "source_last_updated_at": info.source_last_updated_at,
            "steps": steps_json,
        }

    def _write_execution_info_with_duckdb(
        self,
        info: FlowExecutionInfo,
        file_path: Path,
    ) -> None:
        """Write FlowExecutionInfo to Parquet file using DuckDB."""
        import pandas as pd

        record = self._execution_info_to_record(info)
        df = pd.DataFrame([record])

        self.duckdb_engine.write_dataframe_to_parquet(df, file_path, "exec_info")

    def _write_execution_history_with_duckdb(
        self,
        history: FlowExecutionHistory,
        file_path: Path,
    ) -> None:
        """Write FlowExecutionHistory to Parquet file using DuckDB."""
        import pandas as pd

        records = [self._execution_info_to_record(info) for info in history.executions]

        if records:
            df = pd.DataFrame(records)
            self.duckdb_engine.write_dataframe_to_parquet(df, file_path, "exec_history")
        else:
            # Write empty parquet file with schema
            import pyarrow as pa
            import pyarrow.parquet as pq

            from nld.flow.execution.schema import get_execution_history_schema

            schema = get_execution_history_schema()
            empty_table = pa.Table.from_pylist([], schema=schema)
            pq.write_table(empty_table, file_path)

    # DuckDB-specific optimized methods
    def get_execution_count(self) -> int:
        """
        Get execution count via DuckDB SQL query (no full load).

        Returns:
            Number of executions in history.
        """
        execution_history_storage_path = (
            f"{self.backend_state_root_path}/{self.execution_history_file_name}"
        )
        execution_history_file_path = (
            self.local_state_dir / self.execution_history_file_name
        )

        if not self.backend_connector.check_if_file_exists(
            obj_storage_path=execution_history_storage_path
        ):
            return 0

        self.backend_connector.download_file_to_local_path(
            obj_storage_path=execution_history_storage_path,
            local_file_path=str(execution_history_file_path),
        )

        return self.duckdb_engine.count_parquet_rows(execution_history_file_path)

    def supports_optimized_queries(self) -> bool:
        """Indicate that this backend supports optimized DuckDB queries."""
        return True
