from nld.flow.incremental.impl.by_key import (
    ByKeyPlannedProcessingState,
    ByKeyProcessingState,
    ByKeySourceState,
    ByKeyState,
)

from .base import FlowStateManager


class FlowByKeyStateManager(
    FlowStateManager[
        ByKeyState,
        ByKeySourceState,
        ByKeyProcessingState,
        ByKeyPlannedProcessingState,
    ]
):
    """
    Flow State Manager - By Key Incremental

    Manages all the execution and incremental state operations
    """
