from typing import Literal

from nld.utils import NldStrEnum


class FlowUpdateStrategies(NldStrEnum):
    DEL_INS = "DELETE_INSERT"
    DELETE = "DELETE"
    INSERT = "INSERT"
    OVERWRITE = "OVERWRITE"
    UPSERT = "UPSERT"
    UPSERT_LOG_DEL = "UPSERT_LOGICAL_DELETE"
    VIEW = "VIEW"


FLOW_UPDATE_STRATEGY_LITERAL = Literal[
    "DELETE_INSERT",
    "DELETE",
    "INSERT",
    "OVERWRITE",
    "UPSERT",
    "UPSERT_LOGICAL_DELETE",
    "VIEW",
]
