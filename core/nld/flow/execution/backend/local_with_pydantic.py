import os
from pathlib import Path
from typing import Any

from nld.connector.local import LocalFileSystemConnector
from nld.flow.backend.local.backend_mixin import LocalBackendMixin
from nld.flow.execution.events import ExecutionBackendEngineInitialized
from nld.flow.execution.execution_info import (
    FlowExecutionHistory,
    FlowExecutionInfo,
    FlowExecutionState,
    FlowStepExecutionInfo,
)
from nld.flow.execution.manager import (
    ExecutionBackendStateManager,
    steps_from_loaded_executions,
)
from nld.flow.execution.utils import (
    EXECUTION_HISTORY_NAME,
    EXECUTION_INFO_NAME,
    EXECUTION_STATE_NAME,
)
from nld.parameters import ExecutionParameterDefinition


class LocalExecutionPydanticBackendStateManager(
    LocalBackendMixin,
    ExecutionBackendStateManager[LocalFileSystemConnector],
):
    """
    Execution - Local - Backend State Manager using Pydantic.

    Manages all read and write methods for execution state using
    the local filesystem with JSON serialization.
    """

    param_definitions = [
        ExecutionParameterDefinition(
            name="backend_root_path",
            mandatory=True,
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
            ExecutionBackendEngineInitialized(
                backend_type=backend_connector.connection_wrapper.type,
                engine="pydantic",
                manager_class=type(self).__name__,
            ),
        )

    @property
    def execution_info_file_name(self) -> str:
        return f"{EXECUTION_INFO_NAME}.json"

    @property
    def execution_state_file_name(self) -> str:
        return f"{EXECUTION_STATE_NAME}.json"

    @property
    def execution_history_file_name(self) -> str:
        return f"{EXECUTION_HISTORY_NAME}.json"

    @property
    def execution_state_file_path(self) -> Path:
        return Path(
            os.path.join(
                self.backend_state_root_path,
                self.execution_state_file_name,
            )
        )

    @property
    def execution_history_file_path(self) -> Path:
        return Path(
            os.path.join(
                self.backend_state_root_path,
                self.execution_history_file_name,
            )
        )

    def retrieve_latest_execution_state(
        self,
    ) -> tuple[FlowExecutionState, FlowExecutionHistory]:
        """Retrieve the latest execution state from local filesystem."""
        state_path = str(self.execution_state_file_path)
        history_path = str(self.execution_history_file_path)

        if os.path.isfile(state_path) and os.path.isfile(history_path):
            execution_state = FlowExecutionState.read_json_file(state_path)
            execution_history = FlowExecutionHistory.read_json_file(history_path)
            return execution_state, execution_history

        return FlowExecutionState(), FlowExecutionHistory(executions=[])

    def _get_steps_for(self, flow_uid: str) -> list[FlowStepExecutionInfo]:
        """Return the inline steps for an execution stored as a blob."""
        execution_state, execution_history = self.retrieve_latest_execution_state()
        return steps_from_loaded_executions(
            flow_uid=flow_uid,
            execution_state=execution_state,
            execution_history=execution_history,
        )

    def save_execution_info(
        self,
        current_execution_info: FlowExecutionInfo,
        saved_step_names: list[str] | None = None,
    ) -> None:
        """Save the per-execution info file to the local filesystem."""
        processing_info_path = Path(
            os.path.join(
                self.backend_state_for_processing_path,
                self.execution_info_file_name,
            )
        )
        os.makedirs(processing_info_path.parent, exist_ok=True)
        current_execution_info.write_json_file(file_path=processing_info_path)

    def save_execution_history_complete(
        self,
        execution_history: FlowExecutionHistory,
    ) -> None:
        """Rewrite the consolidated execution history file."""
        os.makedirs(self.backend_state_root_path, exist_ok=True)
        execution_history.write_json_file(file_path=self.execution_history_file_path)

    def save_execution_state(
        self,
        current_execution_info: FlowExecutionInfo | None = None,
        new_execution_state: FlowExecutionState | None = None,
    ) -> None:
        """Save the execution state record to the local filesystem."""
        execution_state = new_execution_state or FlowExecutionState(
            last_processed=current_execution_info,
        )
        os.makedirs(self.backend_state_root_path, exist_ok=True)
        execution_state.write_json_file(file_path=self.execution_state_file_path)
