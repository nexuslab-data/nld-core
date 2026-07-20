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
from nld.flow.incremental.models.events import (
    IncrementalMissingParameter,
    IncrementalParameterIgnored,
)
from nld.flow.utils import FlowLoadingStrategies

from .state import (
    ByKeyPlannedProcessingDetailledState,
    ByKeyPlannedProcessingState,
    ByKeyProcessingState,
    ByKeySourceState,
    ByKeyState,
)

LIMIT_PARAM = FlowIncrementalParamDefinition(
    name="limit",
    short_name="limit",
    data_type="int",
    mandatory=False,
    default_value=None,
    allowed_values=None,
)

KEYS_PARAM = FlowIncrementalParamDefinition(
    name="keys",
    short_name="keys",
    data_type="list",
    mandatory=False,
    default_value=None,
    allowed_values=None,
)

BY_KEY_SOURCE_FULL_INCREMENTAL_DEFINITION = FlowIncrementalDefinition(
    default_strategy=FlowLoadingStrategies.DELTA,
    name="BY_KEY_SOURCE_FULL",
    category="by_key",
    source_selection=FlowSourceSelection.BY_KEY,
    target_update_granularity=FlowTargetUpdateGranularity.BY_KEY,
    state_class=ByKeyState,
    source_state_class=ByKeySourceState,
    processing_state_class=ByKeyProcessingState,
    planned_processing_state_class=ByKeyPlannedProcessingState,
    planned_processing_detailled_state_class=ByKeyPlannedProcessingDetailledState,
    auto_processing_state_transition=False,
    partial_state_persistence=True,
    requires_source_state_retrieval=True,
    supports_planned_state=True,
    param_definitions=[
        FULL_FLAG_PARAM,
        KEYS_PARAM,
        LIMIT_PARAM,
        WITH_DELTA_FLAG_PARAM,
    ],
)


class ByKeySourceFullFlowIncrementalParams(FlowIncrementalParams):
    _definition: ClassVar[FlowIncrementalDefinition] = (
        BY_KEY_SOURCE_FULL_INCREMENTAL_DEFINITION
    )
    keys: list[str] | None = None
    limit: int | None = None

    @field_validator("keys", mode="before")
    @classmethod
    def parse_keys_from_string(
        cls,
        value: list[str] | str | None,
    ) -> list[str] | None:
        """Convert a comma-separated string into a list of strings."""
        if isinstance(value, str):
            return [key.strip() for key in value.split(",") if key.strip()]
        return value

    def resolve_strategy(self) -> str:
        if self.full and self.with_delta:
            raise ValueError(
                "The flags '--full' and '--with-delta' are mutually exclusive. "
                "Please provide only one of them."
            )
        if self.full:
            return FlowLoadingStrategies.FULL
        has_backfill_params = self.keys is not None or self.limit is not None
        if has_backfill_params and self.with_delta:
            return FlowLoadingStrategies.BACKFILL_DELTA
        if has_backfill_params:
            return FlowLoadingStrategies.BACKFILL
        return FlowLoadingStrategies.DELTA

    @classmethod
    def get_definition(cls) -> FlowIncrementalDefinition:
        return cls._definition

    def is_incremental_parameters_allowed(self) -> tuple[bool, str]:
        if self.strategy in [
            FlowLoadingStrategies.DELTA,
            FlowLoadingStrategies.FULL,
        ]:
            if self.limit is not None:
                self.log_event(
                    IncrementalParameterIgnored(
                        self.strategy,
                        parameter_name="limit",
                    )
                )
            if self.keys is not None and len(self.keys) > 0:
                self.log_event(
                    IncrementalParameterIgnored(
                        self.strategy,
                        parameter_name="keys",
                    )
                )
            return (True, "")
        elif self.strategy in [FlowLoadingStrategies.BACKFILL_DELTA]:
            if self.limit is None and self.keys is None:
                self.log_event(
                    IncrementalMissingParameter(
                        self.strategy,
                        parameter_names=["limit", "keys"],
                    )
                )
                return (
                    False,
                    "Strategy 'BACKFILL-DELTA' requires at least one of the "
                    "parameters: limit, keys.",
                )
            return (True, "")
        elif self.strategy in [FlowLoadingStrategies.BACKFILL]:
            if self.limit is None and self.keys is None:
                self.log_event(
                    IncrementalMissingParameter(
                        self.strategy,
                        parameter_names=["limit", "keys"],
                    )
                )
                return (
                    False,
                    "Strategy 'BACKFILL' requires at least one of the "
                    "parameters: limit, keys.",
                )
            return (True, "")
        else:
            return (
                False,
                f"Strategy '{self.strategy}' is not supported for 'by_key' "
                f"incremental mode. Supported strategies: "
                f"DELTA, FULL, BACKFILL, BACKFILL-DELTA.",
            )


BY_KEY_SOURCE_FULL_FLOW_INCREMENTAL_LOGIC = FlowIncrementalLogic[
    ByKeySourceFullFlowIncrementalParams
](
    definition=BY_KEY_SOURCE_FULL_INCREMENTAL_DEFINITION,
    parameter_class=ByKeySourceFullFlowIncrementalParams,
)
