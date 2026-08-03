from typing import Literal

from nld.utils import NldStrEnum


class FlowLoadingStrategies(NldStrEnum):
    FULL = "FULL"
    DELTA = "DELTA"
    BACKFILL_DELTA = "BACKFILL-DELTA"
    BACKFILL = "BACKFILL"


FLOW_LOADING_STRATEGIES = [
    FlowLoadingStrategies.FULL.value,
    FlowLoadingStrategies.DELTA.value,
    FlowLoadingStrategies.BACKFILL_DELTA.value,
    FlowLoadingStrategies.BACKFILL.value,
]

FLOW_LOADING_STRATEGY_LITERAL = Literal["FULL", "DELTA", "BACKFILL-DELTA", "BACKFILL"]
