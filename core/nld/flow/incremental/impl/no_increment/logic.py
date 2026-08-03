from typing import ClassVar

from nld.flow.incremental.impl.no_increment.state import (
    NoIncrementPlannedProcessingDetailedState,
    NoIncrementPlannedProcessingState,
    NoIncrementProcessingState,
    NoIncrementSourceState,
    NoIncrementState,
)
from nld.flow.incremental.models import (
    FlowIncrementalDefinition,
    FlowIncrementalLogic,
    FlowIncrementalParams,
    FlowSourceSelection,
    FlowTargetUpdateGranularity,
)
from nld.flow.utils import FlowLoadingStrategies

NO_INCREMENT_INCREMENTAL_DEFINITION = FlowIncrementalDefinition(
    default_strategy=FlowLoadingStrategies.FULL,
    name="NO_INCREMENT",
    category="no_increment",
    source_selection=FlowSourceSelection.NO_SELECTION,
    target_update_granularity=FlowTargetUpdateGranularity.GENERIC,
    state_class=NoIncrementState,
    source_state_class=NoIncrementSourceState,
    processing_state_class=NoIncrementProcessingState,
    planned_processing_state_class=NoIncrementPlannedProcessingState,
    planned_processing_detailed_state_class=NoIncrementPlannedProcessingDetailedState,
    auto_processing_state_transition=True,
    partial_state_persistence=False,
    tracks_logical_deletion=False,
    tracks_state=False,
    param_definitions=[],
)


class NoIncrementFlowIncrementalParams(FlowIncrementalParams):
    _definition: ClassVar[FlowIncrementalDefinition] = (
        NO_INCREMENT_INCREMENTAL_DEFINITION
    )

    def resolve_strategy(self) -> str:
        return FlowLoadingStrategies.FULL

    @classmethod
    def get_definition(cls) -> FlowIncrementalDefinition:
        return cls._definition

    def is_incremental_parameters_allowed(self) -> tuple[bool, str]:
        if self.strategy in [FlowLoadingStrategies.FULL]:
            return (True, "")
        return (
            False,
            f"Strategy '{self.strategy}' is not supported for "
            f"'no_increment' incremental type. "
            f"Supported strategy: FULL.",
        )


NO_INCREMENT_FLOW_INCREMENTAL_LOGIC = FlowIncrementalLogic[
    NoIncrementFlowIncrementalParams
](
    definition=NO_INCREMENT_INCREMENTAL_DEFINITION,
    parameter_class=NoIncrementFlowIncrementalParams,
)
