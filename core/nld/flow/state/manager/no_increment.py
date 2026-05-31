from nld.flow.incremental.impl.no_increment import (
    NoIncrementPlannedProcessingState,
    NoIncrementProcessingState,
    NoIncrementSourceState,
    NoIncrementState,
)

from .base import FlowStateManager


class FlowNoIncrementStateManager(
    FlowStateManager[
        NoIncrementState,
        NoIncrementSourceState,
        NoIncrementProcessingState,
        NoIncrementPlannedProcessingState,
    ]
):
    """
    Flow State Manager - No Increment

    Manages all the execution and incremental state operations
    """
