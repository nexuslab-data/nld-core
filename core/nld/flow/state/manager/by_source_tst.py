from nld.flow.incremental.impl.by_source_tst import (
    BySourceTstPlannedProcessingState,
    BySourceTstProcessingState,
    BySourceTstSourceState,
    BySourceTstState,
)

from .base import FlowStateManager


class FlowBySourceTstStateManager(
    FlowStateManager[
        BySourceTstState,
        BySourceTstSourceState,
        BySourceTstProcessingState,
        BySourceTstPlannedProcessingState,
    ]
):
    """
    Flow State Manager - By Source TST Incremental

    Manages all the execution and incremental state operations.
    Processing state transitions are handled automatically by
    the base FlowStateManager via the
    auto_processing_state_transition flag.
    """
