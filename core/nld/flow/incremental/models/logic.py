import abc
from abc import ABC
from typing import Any

from pydantic import ConfigDict, PrivateAttr

from nld.flow.incremental.models.referential import SourceAvailability
from nld.parameters.execution_params_def import (
    ExecutionParameterDefinition,
)
from nld.pydantic import NldBaseModel
from nld.utils.mixin import NldMixIn


class FlowIncrementalParamDefinition(NldBaseModel):
    name: str
    short_name: str
    data_type: str = "str"
    mandatory: bool = False
    default_value: str | None = None
    allowed_values: list[str] | None = None
    help_text: str = ""

    def to_execution_param_definition(self) -> ExecutionParameterDefinition:
        return ExecutionParameterDefinition(
            name=self.name,
            short_name=self.short_name,
            data_type=self.data_type,
            mandatory=self.mandatory,
            default_value=self.default_value,
            allowed_values=self.allowed_values,
            help_text=self.help_text,
        )


FULL_FLAG_PARAM = FlowIncrementalParamDefinition(
    name="full",
    short_name="full",
    data_type="bool",
    mandatory=False,
    default_value=None,
    help_text="Force FULL loading strategy.",
)

WITH_DELTA_FLAG_PARAM = FlowIncrementalParamDefinition(
    name="with_delta",
    short_name="with_delta",
    data_type="bool",
    mandatory=False,
    default_value=None,
    help_text=(
        "Force DELTA-based loading strategy."
        " Combined with backfill parameters, uses BACKFILL_DELTA."
    ),
)


class FlowIncrementalOptions(NldBaseModel):
    """Base model of the flow-level ``incremental.options`` block.

    Each incremental type accepting options subclasses it. Unknown keys
    are rejected so a typo in a flow YAML fails at load time instead of
    being silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    def check_flow_coherence(self, data_flow_definition: Any) -> list[str]:
        """Return the incoherences between these options and the flow.

        The default accepts every flow. Types override it to check, for
        example, that a configured column exists on the target structure.
        """
        return []


class FlowIncrementalDefinition(NldBaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    default_strategy: str
    name: str
    category: str
    source_selection: str
    # Whether one source read presents the complete extent (see
    # SourceAvailability). Flows can override it per definition in
    # their incremental config; declarative until deletion inference
    # consumes it.
    source_availability: str = SourceAvailability.FULL
    target_update_granularity: str
    state_class: type
    source_state_class: type
    processing_state_class: type
    planned_processing_state_class: type
    planned_processing_detailed_state_class: type
    # When True, the framework automatically transitions the
    # processing state to SUCCEEDED or FAILED based on
    # the outcome of run_flow(). When False, the child task
    # is responsible for updating individual processing
    # states (e.g. per-key in by_key incremental).
    auto_processing_state_transition: bool = False
    # When True, the strategy supports persisting state
    # partially during run_flow() (e.g. per-key). When
    # partial persistence is used, the final bulk state
    # save in post_processing_for_state() is skipped.
    partial_state_persistence: bool = False
    # Step activation flags control which pre/post-processing
    # steps are executed. When False, the step is skipped
    # entirely and no @track_flow_step entry is logged.
    tracks_logical_deletion: bool = True
    tracks_state: bool = True
    requires_source_state_retrieval: bool = False
    # When True, the strategy can precompute a PLANNED processing
    # state that a later run executes from (see PlannedStatePolicy).
    # When False, every run recomputes the processing state and the
    # planned-state CLI commands report that plans are not supported.
    supports_planned_state: bool = False
    # Write strategies a flow of this type may use; None accepts every
    # strategy. Checked at flow load and before every SQL flow write.
    allowed_write_strategies: list[str] | None = None
    # When True, each run owns a scope of the target (e.g. a set of
    # periods): a SQL flow skips its write when the run selects nothing,
    # and hands the scope condition to the scoped write strategies.
    target_scoped: bool = False
    param_definitions: list[FlowIncrementalParamDefinition]
    # Model validating the flow-level ``incremental.options`` block. None
    # means the type accepts no options at all.
    options_model: type[FlowIncrementalOptions] | None = None

    def validate_options(
        self,
        options: dict[str, Any] | None,
    ) -> FlowIncrementalOptions | None:
        """Validate the flow-level options against the options model.

        Raises:
            ValueError: if options are given to a type accepting none, or
                if they do not match the options model.
        """
        if self.options_model is None:
            if options:
                raise ValueError(
                    f"Incremental type '{self.category}' accepts no options, "
                    f"got: {', '.join(sorted(options))}"
                )
            return None
        return self.options_model.model_validate(options or {})

    def create_incremental_parameters(self, **kwargs: Any) -> dict[str, Any]:
        """
        Create incremental parameters for this definition based on arguments.

        Only includes parameters that have an explicit value from kwargs or a
        non-None default, so Pydantic model defaults are used for omitted params.

        :return: A dictionary with arguments from this parameter definitions
        """
        incremental_parameters: dict[str, Any] = {}
        for param_definition in self.param_definitions:
            value = kwargs.pop(param_definition.name, param_definition.default_value)
            if value is not None:
                incremental_parameters[param_definition.name] = value
        return incremental_parameters

    def get_parameters_as_execution_params(
        self,
    ) -> list[ExecutionParameterDefinition]:
        return [
            param_def.to_execution_param_definition()
            for param_def in self.param_definitions
        ]


class FlowIncrementalParams(NldBaseModel, NldMixIn, ABC):  # type: ignore[override]
    _strategy: str | None = PrivateAttr(default=None)
    full: bool = False
    with_delta: bool = False

    @property
    def strategy(self) -> str:
        """Resolve and return the loading strategy."""
        if self._strategy is None:
            self._strategy = self.resolve_strategy()
        return self._strategy

    def model_post_init(self, __context: Any) -> None:
        """Initialize logger after Pydantic initialization."""
        super().model_post_init(__context)
        self._init_logger()

    @abc.abstractmethod
    def resolve_strategy(self) -> str:
        """Determine the loading strategy from the incremental parameters.

        Each subclass implements this to auto-determine the strategy
        based on the provided flags and parameters.
        """
        raise NotImplementedError(
            "The method 'resolve_strategy' should be implemented in sub class."
        )

    @classmethod
    @abc.abstractmethod
    def get_definition(cls) -> FlowIncrementalDefinition:
        raise NotImplementedError(
            "The method 'get_definition' should be implemented in sub class."
        )

    @abc.abstractmethod
    def is_incremental_parameters_allowed(self) -> tuple[bool, str]:
        raise NotImplementedError(
            "Method 'is_incremental_parameters_allowed' should be "
            "implemented in sub class."
        )


class FlowIncrementalLogic[FLOW_INCREMENTAL_PARAMS: "FlowIncrementalParams"](
    NldBaseModel
):
    definition: FlowIncrementalDefinition
    parameter_class: type[FlowIncrementalParams]

    def create_incremental_params_from_dict(
        self,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> FLOW_INCREMENTAL_PARAMS:
        """Build the incremental parameters from runtime values and options.

        The flow-level options are validated and handed to the parameter
        class only for types declaring an options model, since their
        strategy resolution may depend on them.
        """
        incremental_parameters_dict = self.definition.create_incremental_parameters(
            **kwargs
        )
        validated_options = self.definition.validate_options(options=options)
        if validated_options is not None:
            incremental_parameters_dict["options"] = validated_options
        return self.parameter_class(  # type: ignore[return-value]
            **incremental_parameters_dict,
        )
