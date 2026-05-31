import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from nld.connector.s3_blob_storage import S3ObjectStorageConnector
from nld.flow.backend.s3_blob_storage import S3BackendMixin
from nld.flow.execution.backend.s3_blob_storage_base import (
    S3ExecutionBackendStateManagerBase,
)
from nld.flow.execution.events import ExecutionBackendEngineInitialized
from nld.flow.execution.execution_info import (
    FlowExecutionHistory,
    FlowExecutionInfo,
    FlowExecutionState,
)
from nld.flow.execution.schema import (
    get_execution_history_schema,
    get_execution_state_schema,
)
from nld.flow.execution.utils import (
    EXECUTION_HISTORY_NAME,
    EXECUTION_INFO_NAME,
    EXECUTION_STATE_NAME,
)
from nld.parameters import ExecutionParameterDefinition


class S3ExecutionPydanticBackendStateManager(S3ExecutionBackendStateManagerBase):
    """
    Execution - S3 - Backend State Manager using Pydantic/PyArrow.

    Manages all read and write methods for execution state using S3.
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
            ExecutionBackendEngineInitialized(
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
        Download the latest execution state based on file_format.

        Returns:
            Tuple of (FlowExecutionState, FlowExecutionHistory).
        """
        execution_state_storage_path = (
            f"{self.backend_state_root_path}/{self.execution_state_file_name}"
        )
        execution_history_storage_path = (
            f"{self.backend_state_root_path}/{self.execution_history_file_name}"
        )

        if self.backend_connector.check_if_file_exists(
            obj_storage_path=execution_state_storage_path
        ) and self.backend_connector.check_if_file_exists(
            obj_storage_path=execution_history_storage_path
        ):
            # Download and read state
            self.backend_connector.download_file_to_local_path(
                obj_storage_path=execution_state_storage_path,
                local_file_path=str(self.local_execution_state_file_path),
            )
            if self.file_format == "parquet":
                execution_state = self._read_execution_state_from_parquet_row(
                    self.local_execution_state_file_path
                )
            else:
                # Defaults to json
                execution_state = FlowExecutionState.read_json_file(
                    self.local_execution_state_file_path
                )

            # Download and read history
            self.backend_connector.download_file_to_local_path(
                obj_storage_path=execution_history_storage_path,
                local_file_path=str(self.local_execution_history_file_path),
            )
            if self.file_format == "parquet":
                execution_history = self._read_execution_history_from_parquet_row(
                    self.local_execution_history_file_path
                )
            else:
                # Defaults to json
                execution_history = FlowExecutionHistory.read_json_file(
                    self.local_execution_history_file_path
                )
        else:
            # First run
            execution_state = FlowExecutionState()
            execution_history = FlowExecutionHistory(executions=[])

        return execution_state, execution_history

    def _read_execution_info_from_parquet_row(
        self, row: dict[str, Any]
    ) -> FlowExecutionInfo:
        """Convert a Parquet row dict to FlowExecutionInfo."""
        steps_str = row.get("steps")
        steps = json.loads(steps_str) if steps_str else None

        return FlowExecutionInfo(
            flow_uid=row["flow_uid"],
            flow_namespace=row["flow_namespace"],
            flow_name=row["flow_name"],
            flow_instance_name=row["flow_instance_name"],
            requestor=row["requestor"],
            data_load_strategy=row["data_load_strategy"],
            started_at=row.get("started_at"),
            ended_at=row.get("ended_at"),
            execution_status=row.get("execution_status"),
            execution_error=row.get("execution_error"),
            pull_from=row.get("pull_from"),
            pull_to=row.get("pull_to"),
            previous_layer_last_updated_at=row.get("previous_layer_last_updated_at"),
            source_extracted_at=row.get("source_extracted_at"),
            source_last_updated_at=row.get("source_last_updated_at"),
            steps=steps,
        )

    def _read_execution_state_from_parquet_row(
        self, file_path: Path
    ) -> FlowExecutionState:
        """Convert Parquet file to FlowExecutionState."""
        table = pq.read_table(file_path)
        if table.num_rows == 0:
            return FlowExecutionState()

        row = table.to_pydict()
        row_dict = {k: v[0] if v else None for k, v in row.items()}
        last_processed = self._read_execution_info_from_parquet_row(row_dict)
        return FlowExecutionState(last_processed=last_processed)

    def _read_execution_history_from_parquet_row(
        self, file_path: Path
    ) -> FlowExecutionHistory:
        """Convert Parquet file to FlowExecutionHistory."""
        table = pq.read_table(file_path)
        executions: list[FlowExecutionInfo] = []

        for batch in table.to_batches():
            batch_dict = batch.to_pydict()
            for idx in range(batch.num_rows):
                row_dict = {k: v[idx] for k, v in batch_dict.items()}
                executions.append(self._read_execution_info_from_parquet_row(row_dict))

        return FlowExecutionHistory(executions=executions)

    def save_execution_info(
        self,
        current_execution_info: FlowExecutionInfo,
        saved_step_names: list[str] | None = None,
    ) -> None:
        """Save the per-execution info file to S3 based on file_format."""
        if self.file_format == "parquet":
            self._write_execution_info_to_parquet(current_execution_info)
        else:
            self._write_execution_info_to_json(current_execution_info)

    def save_execution_history_complete(
        self,
        execution_history: FlowExecutionHistory,
    ) -> None:
        """Rewrite the consolidated execution history file on S3."""
        if self.file_format == "parquet":
            self._write_execution_history_to_parquet(execution_history)
        else:
            self._write_execution_history_to_json(execution_history)

    def save_execution_state(
        self,
        current_execution_info: FlowExecutionInfo | None = None,
        new_execution_state: FlowExecutionState | None = None,
    ) -> None:
        """Save the execution state record to S3 based on file_format."""
        if self.file_format == "parquet":
            self._write_execution_state_to_parquet(
                current_execution_info,
                new_execution_state=new_execution_state,
            )
        else:
            self._write_execution_state_to_json(
                current_execution_info,
                new_execution_state=new_execution_state,
            )

    def _write_execution_info_to_json(
        self,
        current_execution_info: FlowExecutionInfo,
    ) -> None:
        """Write the per-execution info JSON file on S3."""
        self.local_execution_info_file_path.write_text(
            current_execution_info.model_dump_json(
                indent=4,
                exclude_none=True,
            )
        )
        self._upload_file_to_state_in_process_folder(
            self.local_execution_info_file_path
        )

    def _write_execution_history_to_json(
        self,
        execution_history: FlowExecutionHistory,
    ) -> None:
        """Rewrite the consolidated execution history JSON file on S3."""
        self.local_execution_history_file_path.write_text(
            execution_history.model_dump_json(
                indent=4,
                exclude_none=True,
            )
        )
        self._upload_file_to_state_at_root_folder(
            [self.local_execution_history_file_path]
        )

    def _write_execution_state_to_json(
        self,
        current_execution_info: FlowExecutionInfo | None = None,
        new_execution_state: FlowExecutionState | None = None,
    ) -> None:
        """Write execution state to JSON file on S3."""
        execution_state = new_execution_state or FlowExecutionState(
            last_processed=current_execution_info,
        )
        self.local_execution_state_file_path.write_text(
            execution_state.model_dump_json(
                indent=4,
                exclude_none=True,
            )
        )
        self._upload_file_to_state_at_root_folder(
            [self.local_execution_state_file_path]
        )

    def _write_execution_info_to_parquet(
        self,
        current_execution_info: FlowExecutionInfo,
    ) -> None:
        """Write the per-execution info Parquet file on S3."""
        info_table = self._convert_execution_info_to_pyarrow_table(
            current_execution_info
        )
        pq.write_table(info_table, self.local_execution_info_file_path)
        self._upload_file_to_state_in_process_folder(
            self.local_execution_info_file_path
        )

    def _write_execution_history_to_parquet(
        self,
        execution_history: FlowExecutionHistory,
    ) -> None:
        """Rewrite the consolidated execution history Parquet file on S3."""
        history_table = self._convert_execution_history_to_pyarrow_table(
            execution_history
        )
        pq.write_table(history_table, self.local_execution_history_file_path)
        self._upload_file_to_state_at_root_folder(
            [self.local_execution_history_file_path]
        )

    def _write_execution_state_to_parquet(
        self,
        current_execution_info: FlowExecutionInfo | None = None,
        new_execution_state: FlowExecutionState | None = None,
    ) -> None:
        """Write execution state to Parquet file on S3."""
        state_info = current_execution_info
        if (
            new_execution_state is not None
            and new_execution_state.last_processed is not None
        ):
            state_info = new_execution_state.last_processed
        assert state_info is not None
        state_table = self._convert_execution_info_to_pyarrow_table(
            state_info,
        )
        pq.write_table(state_table, self.local_execution_state_file_path)
        self._upload_file_to_state_at_root_folder(
            [self.local_execution_state_file_path]
        )

    def _convert_execution_info_to_pyarrow_dict(
        self, info: FlowExecutionInfo
    ) -> dict[str, Any]:
        """Convert FlowExecutionInfo to a dict for PyArrow."""
        # Use the default ("python") dump so datetime / Decimal values
        # survive as native objects. ``mode="json"`` would coerce
        # datetimes to ISO strings, which PyArrow then rejects against
        # the ``pa.timestamp("us", tz="UTC")`` columns with
        # ``ArrowTypeError: object of type str cannot be converted to int``.
        data = info.model_dump()
        # The steps column is stored as a JSON string in parquet;
        # ``default=str`` handles datetime / Decimal inside the nested
        # step dicts.
        if data.get("steps"):
            data["steps"] = json.dumps(data["steps"], default=str)
        return data

    def _convert_execution_info_to_pyarrow_table(
        self, info: FlowExecutionInfo
    ) -> pa.Table:
        """Convert FlowExecutionInfo to PyArrow Table."""
        record = self._convert_execution_info_to_pyarrow_dict(info)
        return pa.Table.from_pylist([record], schema=get_execution_state_schema())

    def _convert_execution_history_to_pyarrow_table(
        self, history: FlowExecutionHistory
    ) -> pa.Table:
        """Convert FlowExecutionHistory to PyArrow Table."""
        records = [
            self._convert_execution_info_to_pyarrow_dict(info)
            for info in history.executions
        ]
        return pa.Table.from_pylist(records, schema=get_execution_history_schema())
