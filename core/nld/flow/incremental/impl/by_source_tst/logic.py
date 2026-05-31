import datetime
from typing import ClassVar

from pydantic import field_validator

from nld.flow.incremental.models import (
    FULL_FLAG_PARAM,
    WITH_DELTA_FLAG_PARAM,
    FlowIncrementalDefinition,
    FlowIncrementalLogic,
    FlowIncrementalParamDefinition,
    FlowIncrementalParams,
    FlowSourceSelection,
    FlowTargetUpdateGranularity,
)
from nld.flow.incremental.models.events import IncrementalParameterIgnored
from nld.flow.utils import FlowLoadingStrategies
from nld.utils.datetime_util import ensure_utc_datetime, parse_datetime_string

from .state import (
    BySourceTstPlannedProcessingState,
    BySourceTstProcessingState,
    BySourceTstSourceState,
    BySourceTstState,
)

PULL_FROM_PARAM = FlowIncrementalParamDefinition(
    name="pull_from",
    short_name="pull_from",
    data_type="datetime",
    mandatory=False,
    default_value=None,
    help_text="Override the start of the pull range (UTC datetime).",
)

PULL_TO_PARAM = FlowIncrementalParamDefinition(
    name="pull_to",
    short_name="pull_to",
    data_type="datetime",
    mandatory=False,
    default_value=None,
    help_text="Override the end of the pull range (UTC datetime).",
)

BY_SOURCE_TST_INCREMENTAL_DEFINITION = FlowIncrementalDefinition(
    default_strategy=FlowLoadingStrategies.DELTA,
    name="BY_SOURCE_TST",
    category="by_source_tst",
    source_selection=FlowSourceSelection.BY_SOURCE_TST,
    target_update_granularity=FlowTargetUpdateGranularity.GENERIC,
    state_class=BySourceTstState,
    source_state_class=BySourceTstSourceState,
    processing_state_class=BySourceTstProcessingState,
    planned_processing_state_class=BySourceTstPlannedProcessingState,
    auto_processing_state_transition=True,
    partial_state_persistence=False,
    tracks_logical_deletion=False,
    supports_planned_state=True,
    param_definitions=[
        FULL_FLAG_PARAM,
        PULL_FROM_PARAM,
        PULL_TO_PARAM,
        WITH_DELTA_FLAG_PARAM,
    ],
)


class BySourceTstFlowIncrementalParams(FlowIncrementalParams):
    _definition: ClassVar[FlowIncrementalDefinition] = (
        BY_SOURCE_TST_INCREMENTAL_DEFINITION
    )
    pull_from: datetime.datetime | None = None
    pull_to: datetime.datetime | None = None

    @field_validator(
        "pull_from",
        "pull_to",
        mode="before",
    )
    @classmethod
    def parse_and_validate_utc_datetime(
        cls,
        value: datetime.datetime | str | None,
    ) -> datetime.datetime | None:
        """Parse string inputs and enforce UTC timezone."""
        if value is None:
            return None
        if isinstance(value, str):
            return parse_datetime_string(value)
        return ensure_utc_datetime(value)

    def resolve_strategy(self) -> str:
        if self.full:
            return FlowLoadingStrategies.FULL
        if self.pull_from is not None and self.pull_to is not None:
            return FlowLoadingStrategies.BACKFILL
        if self.pull_from is not None:
            return FlowLoadingStrategies.BACKFILL_DELTA
        return FlowLoadingStrategies.DELTA

    @classmethod
    def get_definition(cls) -> FlowIncrementalDefinition:
        return cls._definition

    def is_incremental_parameters_allowed(self) -> tuple[bool, str]:
        if self.strategy in [
            FlowLoadingStrategies.DELTA,
            FlowLoadingStrategies.FULL,
        ]:
            if self.pull_from is not None:
                self.log_event(
                    IncrementalParameterIgnored(
                        self.strategy,
                        parameter_name="pull_from",
                    )
                )
            if self.pull_to is not None:
                self.log_event(
                    IncrementalParameterIgnored(
                        self.strategy,
                        parameter_name="pull_to",
                    )
                )
            return (True, "")
        if self.strategy in [
            FlowLoadingStrategies.BACKFILL,
            FlowLoadingStrategies.BACKFILL_DELTA,
        ]:
            return (True, "")
        return (
            False,
            f"Strategy '{self.strategy}' is not supported for "
            f"'by_source_tst' incremental mode. "
            f"Supported strategies: DELTA, FULL, BACKFILL, BACKFILL-DELTA.",
        )


BY_SOURCE_TST_FLOW_INCREMENTAL_LOGIC = FlowIncrementalLogic[
    BySourceTstFlowIncrementalParams
](
    definition=BY_SOURCE_TST_INCREMENTAL_DEFINITION,
    parameter_class=BySourceTstFlowIncrementalParams,
)
