import abc
from typing import Any

from nld.connector.base.connector import DataConnector
from nld.flow.incremental.base.manager import (
    IncrementalBackendStateManager,
)
from nld.flow.incremental.impl.by_target_period.state import (
    ByTargetPeriodPlannedProcessingDetailedState,
    ByTargetPeriodPlannedProcessingState,
    ByTargetPeriodProcessingState,
    ByTargetPeriodSourceState,
    ByTargetPeriodState,
)


class ByTargetPeriodStateBackendManager[DATA_CONNECTOR: DataConnector[Any]](
    IncrementalBackendStateManager[
        DATA_CONNECTOR,
        ByTargetPeriodState,
        ByTargetPeriodSourceState,
        ByTargetPeriodProcessingState,
        ByTargetPeriodPlannedProcessingState,
        ByTargetPeriodPlannedProcessingDetailedState,
    ],
    abc.ABC,
):
    pass
