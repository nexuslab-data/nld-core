import abc
from typing import Any

from nld.connector.base.connector import DataConnector
from nld.flow.incremental.base.manager import (
    IncrementalBackendStateManager,
)
from nld.flow.incremental.impl.by_key.state import (
    ByKeyPlannedProcessingDetailledState,
    ByKeyPlannedProcessingState,
    ByKeyProcessingState,
    ByKeySourceState,
    ByKeyState,
)


class ByKeyStateBackendManager[DATA_CONNECTOR: DataConnector[Any]](
    IncrementalBackendStateManager[
        DATA_CONNECTOR,
        ByKeyState,
        ByKeySourceState,
        ByKeyProcessingState,
        ByKeyPlannedProcessingState,
        ByKeyPlannedProcessingDetailledState,
    ],
    abc.ABC,
):
    pass
