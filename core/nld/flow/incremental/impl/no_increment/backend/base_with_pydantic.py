from typing import Any

from nld.connector.base.connector import DataConnector
from nld.flow.incremental.base.manager import (
    IncrementalBackendStateManager,
)
from nld.flow.incremental.impl.no_increment.state import (
    NoIncrementPlannedProcessingDetailedState,
    NoIncrementPlannedProcessingState,
    NoIncrementProcessingState,
    NoIncrementSourceState,
    NoIncrementState,
)


class NoIncrementStateBackendManager[DATA_CONNECTOR: DataConnector[Any]](
    IncrementalBackendStateManager[
        DATA_CONNECTOR,
        NoIncrementState,
        NoIncrementSourceState,
        NoIncrementProcessingState,
        NoIncrementPlannedProcessingState,
        NoIncrementPlannedProcessingDetailedState,
    ],
):
    """
    No Increment - Standard - Backend State Manager

    The no increment incremental logic should not do anything. It is
    present to ensure compatibility with all the other incremental logics.
    """

    def read_current_state(self) -> NoIncrementState:
        return NoIncrementState()

    def write_processing_state(
        self,
        processing_flow_state: NoIncrementProcessingState,
    ) -> None:
        pass

    def write_post_processing_state(
        self, post_processing_flow_state: NoIncrementState
    ) -> None:
        pass
