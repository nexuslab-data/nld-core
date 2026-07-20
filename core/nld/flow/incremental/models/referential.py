from typing import Literal

from nld.utils import NldStrEnum

# Incremental definition


class SourceAvailability(NldStrEnum):
    ALWAYS_FULL = "ALWAYS_FULL"
    PARTIALLY_AVAILABLE = "PARTIALLY_AVAILABLE"


class FlowSourceSelection(NldStrEnum):
    NO_SELECTION = "NO_SELECTION"
    BY_KEY = "BY_KEY"
    BY_SOURCE_TST = "BY_SOURCE_TST"


class FlowTargetUpdateGranularity(NldStrEnum):
    GENERIC = "GENERIC"
    BY_KEY = "BY_KEY"
    BY_DAY = "BY_DAY"


# State status


class IncrementalStateStatus:
    NOT_PROCESSED = "NOT_PROCESSED"
    DELETED = "DELETED"
    FAILED = "FAILED"
    SUCCEEDED = "SUCCEEDED"
    # Terminal: the source authoritatively answered that this key does not
    # exist (e.g. a deterministic 404). Like SUCCEEDED, it is never re-attempted
    # by DELTA/BACKFILL_DELTA; FULL and explicit --keys still re-attempt it.
    PERMANENTLY_EXCLUDED = "PERMANENTLY_EXCLUDED"


class IncrementalProcessingStatus:
    EXCLUDED = "EXCLUDED"
    TO_BE_PROCESSED = "TO_BE_PROCESSED"
    TO_BE_DELETED = "TO_BE_DELETED"
    FAILED = "FAILED"
    SUCCEEDED = "SUCCEEDED"
    # The task determined during the run that the source does not expose this
    # key at all; persisted as IncrementalStateStatus.PERMANENTLY_EXCLUDED.
    # Distinct from EXCLUDED, which is a per-run selection (budget/keys filter)
    # that leaves the persisted state untouched.
    PERMANENTLY_EXCLUDED = "PERMANENTLY_EXCLUDED"


INCREMENTAL_PROCESSING_STATUS = [
    IncrementalProcessingStatus.EXCLUDED,
    IncrementalProcessingStatus.TO_BE_PROCESSED,
    IncrementalProcessingStatus.TO_BE_DELETED,
    IncrementalProcessingStatus.FAILED,
    IncrementalProcessingStatus.SUCCEEDED,
    IncrementalProcessingStatus.PERMANENTLY_EXCLUDED,
]


class IncrementalPlanStatus:
    PLANNED = "PLANNED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


INCREMENTAL_PLAN_STATUS = [
    IncrementalPlanStatus.CANCELLED,
    IncrementalPlanStatus.COMPLETED,
    IncrementalPlanStatus.PLANNED,
]


# General referential


class FlowIncrementalType(NldStrEnum):
    FULL = "FULL"
    ON_SOURCE_TECHNICAL_TST = "ON_SOURCE_TECHNICAL_TST"
    ON_SOURCE_TECHNICAL_TST_FIXED_SELECTION_RANGE = (
        "ON_SOURCE_TECHNICAL_TST_FIXED_SELECTION_RANGE"
    )
    ON_TARGET_FUNCTIONAL_KEY = "ON_TARGET_FUNCTIONAL_KEY"
    ON_TARGET_FUNCTIONAL_KEY_BASED_ON_SOURCE_TST = (
        "ON_TARGET_FUNCTIONAL_KEY_BASED_ON_SOURCE_TST"
    )
    ON_TARGET_FUNCTIONAL_DATE_RANGE_BASED_ON_SOURCE_TST = (
        "ON_TARGET_FUNCTIONAL_DATE_RANGE_BASED_ON_SOURCE_TST"
    )
    ON_TARGET_FUNCTIONAL_MONTH_RANGE_BASED_ON_SOURCE_TST = (
        "ON_TARGET_FUNCTIONAL_MONTH_RANGE_BASED_ON_SOURCE_TST"
    )


FLOW_INCREMENTAL_TYPE_LITERAL = Literal[
    "FULL",
    "ON_SOURCE_TECHNICAL_TST",
    "ON_SOURCE_TECHNICAL_TST_FIXED_SELECTION_RANGE",
    "ON_TARGET_FUNCTIONAL_KEY",
    "ON_TARGET_FUNCTIONAL_KEY_BASED_ON_SOURCE_TST",
    "ON_TARGET_FUNCTIONAL_DATE_RANGE_BASED_ON_SOURCE_TST",
    "ON_TARGET_FUNCTIONAL_MONTH_RANGE_BASED_ON_SOURCE_TST",
]


class FlowIncrementalPeriodRangeType(NldStrEnum):
    HOURS = "HOURS"
    DAYS = "DAYS"
    MONTHS = "MONTHS"
    YEARS = "YEARS"
    FIXED_DAYS = "FIXED_DAYS"


FLOW_INCREMENTAL_PERIOD_RANGE_TYPE_LITERAL = Literal[
    "HOURS", "DAYS", "MONTHS", "YEARS", "FIXED_DAYS"
]
