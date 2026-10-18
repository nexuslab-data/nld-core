import os
from pathlib import Path
from typing import Any

from nld.connector.local import LocalFileSystemConnector
from nld.flow.backend.local.backend_mixin import LocalBackendMixin
from nld.flow.incremental.impl.by_target_period.backend.base_with_pydantic import (
    ByTargetPeriodStateBackendManager,
)
from nld.flow.incremental.impl.by_target_period.constants import (
    GENERAL_STATE_NAME,
    PROCESSED_STATE_NAME,
)
from nld.flow.incremental.impl.by_target_period.state import (
    ByTargetPeriodProcessingState,
    ByTargetPeriodState,
)
from nld.flow.incremental.models.events import (
    IncrementalBackendEngineInitialized,
)
from nld.parameters import ExecutionParameterDefinition


class LocalByTargetPeriodPydanticStateBackendManager(
    LocalBackendMixin,
    ByTargetPeriodStateBackendManager[LocalFileSystemConnector],
):
    """
    BY_TARGET_PERIOD State Backend Manager for local filesystem using Pydantic.

    Persists the period state and the last processing state as JSON files
    on the local filesystem.
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
            IncrementalBackendEngineInitialized(
                backend_type=backend_connector.connection_wrapper.type,
                engine="pydantic",
                manager_class=type(self).__name__,
            ),
        )

    @property
    def general_state_file_path(self) -> Path:
        return Path(
            os.path.join(
                self.backend_state_root_path,
                f"{GENERAL_STATE_NAME}.json",
            )
        )

    @property
    def processed_state_file_path(self) -> Path:
        return Path(
            os.path.join(
                self.backend_state_for_processing_path,
                f"{PROCESSED_STATE_NAME}.json",
            )
        )

    def read_current_state(self) -> ByTargetPeriodState:
        """Retrieve the current period state from the local filesystem."""
        state = self.read_post_processing_state()
        return state if state is not None else ByTargetPeriodState()

    def read_post_processing_state(self) -> ByTargetPeriodState | None:
        """Read the persisted period state, None when never written."""
        if not self.general_state_file_path.is_file():
            return None
        return ByTargetPeriodState.model_validate_json(
            self.general_state_file_path.read_text(encoding="utf-8"),
        )

    def read_processing_state(self) -> ByTargetPeriodProcessingState | None:
        """Read the processing state of the last run, None when never written."""
        if not self.processed_state_file_path.is_file():
            return None
        return ByTargetPeriodProcessingState.model_validate_json(
            self.processed_state_file_path.read_text(encoding="utf-8"),
        )

    def write_processing_state(
        self,
        processing_flow_state: ByTargetPeriodProcessingState,
    ) -> None:
        """Write processing state as JSON to the processing folder."""
        os.makedirs(self.processed_state_file_path.parent, exist_ok=True)
        processing_flow_state.write_json_file(
            file_path=self.processed_state_file_path,
        )

    def write_post_processing_state(
        self,
        post_processing_flow_state: ByTargetPeriodState,
    ) -> None:
        """Write post-processing state as JSON to the root state folder."""
        os.makedirs(self.general_state_file_path.parent, exist_ok=True)
        post_processing_flow_state.write_json_file(
            file_path=self.general_state_file_path,
        )
