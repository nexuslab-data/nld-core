from typing import Literal

from nld.utils import NldStrEnum


class FlowUpdateStrategies(NldStrEnum):
    DEL_INS = "DELETE_INSERT"
    DEL_INS_SCOPED = "DELETE_INSERT_SCOPED"
    INSERT = "INSERT"
    OVERWRITE = "OVERWRITE"
    UPSERT = "UPSERT"
    UPSERT_LOG_DEL = "UPSERT_LOGICAL_DELETE"
    VIEW = "VIEW"


FLOW_UPDATE_STRATEGY_LITERAL = Literal[
    "DELETE_INSERT",
    "DELETE_INSERT_SCOPED",
    "INSERT",
    "OVERWRITE",
    "UPSERT",
    "UPSERT_LOGICAL_DELETE",
    "VIEW",
]


class OverwriteModes(NldStrEnum):
    REPLACE = "replace"
    TRUNCATE_INSERT = "truncate_insert"


OVERWRITE_MODE_LITERAL = Literal[
    "replace",
    "truncate_insert",
]
