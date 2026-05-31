import datetime
import json
import os
from pathlib import Path
from typing import Any

from nld.connector.local import LocalFileSystemConnector
from nld.flow.backend.local.backend_mixin import LocalBackendMixin
from nld.flow.incremental.impl.by_source_tst.backend.base_with_pydantic import (
    BySourceTstStateBackendManager,
)
from nld.flow.incremental.impl.by_source_tst.state import (
    BySourceTstProcessingState,
    BySourceTstState,
)
from nld.flow.incremental.models import (
    GENERAL_STATE_NAME,
    PROCESSED_STATE_NAME,
)
from nld.flow.incremental.models.events import (
    IncrementalBackendEngineInitialized,
)
from nld.parameters import ExecutionParameterDefinition


class LocalBySourceTstPydanticStateBackendManager(
    LocalBackendMixin,
    BySourceTstStateBackendManager[LocalFileSystemConnector],
):
    """
    BY_SOURCE_TST State Backend Manager for local filesystem using Pydantic.

    Manages all read and write methods for by_source_tst incremental state
    using JSON serialization on the local filesystem.
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

    def read_current_state(self) -> BySourceTstState:
        """Retrieve the current state from local filesystem."""
        file_path = str(self.general_state_file_path)
        if os.path.isfile(file_path):
            raw = json.loads(Path(file_path).read_text(encoding="utf-8"))
            for field_name in ("last_pull_to_timestamp",):
                if raw.get(field_name):
                    raw[field_name] = datetime.datetime.fromisoformat(raw[field_name])
            return BySourceTstState(**raw)
        return BySourceTstState()

    def write_processing_state(
        self,
        processing_flow_state: BySourceTstProcessingState,
    ) -> None:
        """Write processing state as JSON to the processing folder."""
        os.makedirs(self.processed_state_file_path.parent, exist_ok=True)
        processing_flow_state.write_json_file(
            file_path=self.processed_state_file_path,
        )

    def write_post_processing_state(
        self,
        post_processing_flow_state: BySourceTstState,
    ) -> None:
        """Write post-processing state as JSON to the root state folder."""
        os.makedirs(self.general_state_file_path.parent, exist_ok=True)
        post_processing_flow_state.write_json_file(
            file_path=self.general_state_file_path,
        )
