import abc
from typing import Any

from nld.connector.base.connector import DataConnector
from nld.flow.incremental.base.manager import (
    IncrementalBackendStateManager,
)
from nld.flow.incremental.impl.by_source_tst.state import (
    BySourceTstPlannedProcessingState,
    BySourceTstProcessingState,
    BySourceTstSourceState,
    BySourceTstState,
)


class BySourceTstStateBackendManager[DATA_CONNECTOR: DataConnector[Any]](
    IncrementalBackendStateManager[
        DATA_CONNECTOR,
        BySourceTstState,
        BySourceTstSourceState,
        BySourceTstProcessingState,
        BySourceTstPlannedProcessingState,
    ],
    abc.ABC,
):
    pass
