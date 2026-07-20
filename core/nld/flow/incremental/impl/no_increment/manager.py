from typing import Any

from nld.connector.base.connector import DataConnector
from nld.flow.incremental.base.manager import (
    IncrementalBackendStateManager,
    IncrementalStateManager,
)
from nld.flow.incremental.base.sql_filter_manager import IncrementalSqlFilterManager
from nld.flow.incremental.impl.no_increment.logic import (
    NO_INCREMENT_FLOW_INCREMENTAL_LOGIC,
    NoIncrementFlowIncrementalParams,
)
from nld.flow.incremental.impl.no_increment.sql_filter_manager import (
    NoIncrementSqlFilterManager,
)
from nld.flow.incremental.impl.no_increment.state import (
    NoIncrementPlannedProcessingDetailledState,
    NoIncrementPlannedProcessingState,
    NoIncrementProcessingState,
    NoIncrementSourceState,
    NoIncrementState,
)


class NoIncrementStateManager(
    IncrementalStateManager[
        NoIncrementState,
        NoIncrementSourceState,
        NoIncrementProcessingState,
        NoIncrementPlannedProcessingState,
        NoIncrementFlowIncrementalParams,
    ]
):
    flow_incremental_logic = NO_INCREMENT_FLOW_INCREMENTAL_LOGIC

    def __init__(
        self,
        incremental_parameters: NoIncrementFlowIncrementalParams,
        incremental_state_backend_manager: IncrementalBackendStateManager[
            DataConnector[Any],
            NoIncrementState,
            NoIncrementSourceState,
            NoIncrementProcessingState,
            NoIncrementPlannedProcessingState,
            NoIncrementPlannedProcessingDetailledState,
        ]
        | None = None,
        secondary_incremental_state_backend_manager: IncrementalBackendStateManager[
            DataConnector[Any],
            NoIncrementState,
            NoIncrementSourceState,
            NoIncrementProcessingState,
            NoIncrementPlannedProcessingState,
            NoIncrementPlannedProcessingDetailledState,
        ]
        | None = None,
        parameters: dict[str, Any] | None = None,
    ):
        super().__init__(
            incremental_parameters=incremental_parameters,
            incremental_state_backend_manager=incremental_state_backend_manager,
            secondary_incremental_state_backend_manager=(
                secondary_incremental_state_backend_manager
            ),
            parameters=parameters,
        )
        self.processing_state: NoIncrementProcessingState

    @property
    def sql_filter_manager(self) -> IncrementalSqlFilterManager:
        """Return the no-op SQL filter."""
        return NoIncrementSqlFilterManager()

    def init_processing_state(self) -> None:
        pass

    def update_processing_state(self) -> None:
        pass

    def create_post_processing_state(self) -> NoIncrementState:
        return NoIncrementState()
