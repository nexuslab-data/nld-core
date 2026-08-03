import json
import os
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from nld.connector.local import LocalFileSystemConnector
from nld.flow.backend.local.backend_mixin import LocalBackendMixin
from nld.flow.incremental.impl.by_key.backend.base_with_pydantic import (
    ByKeyStateBackendManager,
)
from nld.flow.incremental.impl.by_key.constants import (
    GENERAL_STATE_NAME,
    PROCESSED_STATE_NAME,
)
from nld.flow.incremental.impl.by_key.schema import get_by_key_state_schema
from nld.flow.incremental.impl.by_key.state import (
    ByKeyProcessingState,
    ByKeySingleKeyState,
    ByKeyState,
)
from nld.flow.incremental.models.events import (
    IncrementalBackendEngineInitialized,
)
from nld.parameters import ExecutionParameterDefinition


class LocalByKeyPydanticStateBackendManager(
    LocalBackendMixin,
    ByKeyStateBackendManager[LocalFileSystemConnector],
):
    """
    BY_KEY State Backend Manager for local filesystem using Pydantic/PyArrow.

    Supports both JSON and Parquet formats for state persistence on
    the local filesystem.
    """

    param_definitions = [
        ExecutionParameterDefinition(
            name="backend_root_path",
            mandatory=True,
        ),
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
        self.log_event(
            IncrementalBackendEngineInitialized(
                backend_type=backend_connector.connection_wrapper.type,
                engine="pydantic",
                manager_class=type(self).__name__,
            ),
        )

    @property
    def file_format(self) -> str:
        return self.parameters["file_format"]  # type: ignore[no-any-return]

    @property
    def file_extension(self) -> str:
        return "parquet" if self.file_format == "parquet" else "json"

    @property
    def general_state_file_name(self) -> str:
        return f"{GENERAL_STATE_NAME}.{self.file_extension}"

    @property
    def processed_state_file_name(self) -> str:
        return f"{PROCESSED_STATE_NAME}.{self.file_extension}"

    @property
    def general_state_file_path(self) -> Path:
        return Path(
            os.path.join(
                self.backend_state_root_path,
                self.general_state_file_name,
            )
        )

    @property
    def processed_state_file_path(self) -> Path:
        return Path(
            os.path.join(
                self.backend_state_for_processing_path,
                self.processed_state_file_name,
            )
        )

    def read_current_state(self) -> ByKeyState:
        """Retrieve the current state from local filesystem."""
        if self.file_format == "parquet":
            return self._read_from_parquet()
        return self._read_from_json()

    def _read_from_json(self) -> ByKeyState:
        """Read state from JSON file on local filesystem."""
        file_path = str(self.general_state_file_path)
        if os.path.isfile(file_path):
            return ByKeyState.read_json_file(file_path)
        return ByKeyState(keys={})

    def _read_from_parquet(self) -> ByKeyState:
        """Read state from Parquet file on local filesystem."""
        file_path = str(self.general_state_file_path)
        if os.path.isfile(file_path):
            return self._parquet_to_by_key_state(Path(file_path))
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
        """Write the processing state as JSON to the processing folder."""
        os.makedirs(self.processed_state_file_path.parent, exist_ok=True)
        processing_flow_state.write_json_file(
            file_path=self.processed_state_file_path,
        )

    def write_post_processing_state(
        self,
        post_processing_flow_state: ByKeyState,
    ) -> None:
        """Write post-processing state to the root state folder."""
        if self.file_format == "parquet":
            self._write_to_parquet(post_processing_flow_state)
        else:
            self._write_to_json(post_processing_flow_state)

    def _write_to_json(self, state: ByKeyState) -> None:
        """Write state as JSON to the root state folder."""
        os.makedirs(self.general_state_file_path.parent, exist_ok=True)
        state.write_json_file(file_path=self.general_state_file_path)

    def _write_to_parquet(self, state: ByKeyState) -> None:
        """Write state as Parquet to the root state folder."""
        table = self._convert_by_key_state_to_parquet(state)
        os.makedirs(self.general_state_file_path.parent, exist_ok=True)
        pq.write_table(table, where=self.general_state_file_path)

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

        return pa.Table.from_pylist(
            records,
            schema=get_by_key_state_schema(),
        )
