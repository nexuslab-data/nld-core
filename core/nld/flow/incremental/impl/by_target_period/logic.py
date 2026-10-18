from typing import Any, ClassVar

from pydantic import field_validator, model_validator

from nld.flow.definition.flow_definition import resolve_master_predecessors
from nld.flow.incremental.impl.by_target_period.period import (
    PeriodCalendar,
    PeriodGranularity,
    PeriodWeekStart,
    resolve_week_start,
    validate_period_timezone,
)
from nld.flow.incremental.impl.by_target_period.state import (
    ByTargetPeriodPlannedProcessingDetailedState,
    ByTargetPeriodPlannedProcessingState,
    ByTargetPeriodProcessingState,
    ByTargetPeriodSourceState,
    ByTargetPeriodState,
)
from nld.flow.incremental.models import (
    FULL_FLAG_PARAM,
    WITH_DELTA_FLAG_PARAM,
    FlowIncrementalDefinition,
    FlowIncrementalLogic,
    FlowIncrementalOptions,
    FlowIncrementalParamDefinition,
    FlowIncrementalParams,
    FlowSourceSelection,
    FlowTargetUpdateGranularity,
)
from nld.flow.incremental.models.events import IncrementalParameterIgnored
from nld.flow.utils import FlowLoadingStrategies
from nld.flow.utils.flow_update_strategy import FlowUpdateStrategies
from nld.utils import NldStrEnum

DEFAULT_LOOKBACK_PERIODS = 1

# Write strategies replacing or merging the processed periods only. The
# others need the full source extent (OVERWRITE, UPSERT_LOGICAL_DELETE)
# or write no table at all (VIEW).
BY_TARGET_PERIOD_ALLOWED_WRITE_STRATEGIES: list[str] = [
    FlowUpdateStrategies.DEL_INS,
    FlowUpdateStrategies.DEL_INS_SCOPED,
    FlowUpdateStrategies.INSERT,
    FlowUpdateStrategies.UPSERT,
]


class PeriodPerimeter(NldStrEnum):
    """Where the periods a DELTA run replaces come from.

    ``declared``: only from the runtime parameters, which are mandatory.
    ``discovered``: from a scan of the source for the periods modified
    since the last scan. ``rolling``: from a window of the last periods
    relative to the run date (e.g. yesterday for a daily flow).
    """

    DECLARED = "declared"
    DISCOVERED = "discovered"
    ROLLING = "rolling"


class ByTargetPeriodOptions(FlowIncrementalOptions):
    """The ``incremental.options`` block of a by_target_period flow.

    Example of a daily flow reloading yesterday on each run::

        incremental:
          type: by_target_period
          options:
            perimeter: rolling
            granularity: DAY
            period_field: dt_order
    """

    granularity: str
    include_current_period: bool | None = None
    lookback_periods: int | None = None
    max_periods_per_run: int | None = None
    perimeter: str
    # Column holding the period on the target, used by the scoped delete.
    period_field: str
    period_timezone: str = "UTC"
    # Modification timestamp scanned on the MASTER predecessors; defaults
    # to their REC_LAST_UPDATE_TST characterised field.
    scan_field: str | None = None
    # Column holding the period on the MASTER predecessors; defaults to
    # ``period_field`` when both sides share the column name.
    source_period_field: str | None = None
    # First day of a WEEK period; ISO weeks (MONDAY) when not set.
    week_start: str | None = None

    @field_validator("perimeter", mode="before")
    @classmethod
    def validate_perimeter(cls, value: Any) -> str:
        """Accept a perimeter in any case and store it lowercase."""
        return PeriodPerimeter(str(value).lower()).value

    @field_validator("granularity", mode="before")
    @classmethod
    def validate_granularity(cls, value: Any) -> str:
        """Accept a granularity in any case and store it uppercase."""
        return PeriodGranularity(str(value).upper()).value

    @field_validator("week_start", mode="before")
    @classmethod
    def validate_week_start(cls, value: Any) -> str | None:
        """Accept a week start in any case and store it uppercase."""
        if value is None:
            return None
        return PeriodWeekStart(str(value).upper()).value

    @field_validator("period_field", "source_period_field", "scan_field")
    @classmethod
    def validate_field_name(cls, value: str | None) -> str | None:
        """Reject blank column names."""
        if value is not None and not value.strip():
            raise ValueError("a column name must not be blank")
        return value

    @field_validator("period_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        """Reject unknown IANA timezones."""
        return validate_period_timezone(value)

    @field_validator("lookback_periods", "max_periods_per_run")
    @classmethod
    def validate_positive(cls, value: int | None) -> int | None:
        """Reject counts lower than one."""
        if value is not None and value < 1:
            raise ValueError("the value must be greater than or equal to 1")
        return value

    @model_validator(mode="after")
    def validate_rolling_only_options(self) -> "ByTargetPeriodOptions":
        """Reject the rolling window options on another perimeter."""
        if self.perimeter == PeriodPerimeter.ROLLING:
            return self
        for option_name in ("lookback_periods", "include_current_period"):
            if getattr(self, option_name) is not None:
                raise ValueError(
                    f"'{option_name}' only applies to the 'rolling' perimeter"
                )
        return self

    @model_validator(mode="after")
    def validate_week_only_options(self) -> "ByTargetPeriodOptions":
        """Reject a week start on a calendar that is not weekly."""
        if self.week_start is not None and self.granularity != PeriodGranularity.WEEK:
            raise ValueError("'week_start' only applies to the 'WEEK' granularity")
        return self

    @property
    def calendar(self) -> PeriodCalendar:
        return PeriodCalendar(
            granularity=self.granularity,
            timezone=self.period_timezone,
            week_start=self.get_week_start() or PeriodWeekStart.MONDAY,
        )

    def get_week_start(self) -> str | None:
        """Return the first day of the week, None when the calendar is not weekly."""
        return resolve_week_start(
            self.granularity,
            week_start=self.week_start,
        )

    def get_source_period_field(self) -> str:
        return self.source_period_field or self.period_field

    def get_lookback_periods(self) -> int:
        return self.lookback_periods or DEFAULT_LOOKBACK_PERIODS

    def check_flow_coherence(self, data_flow_definition: Any) -> list[str]:
        """Check the options against the predecessors, target and write strategy.

        Structures are resolved best-effort: outside a loaded entity
        registry they cannot resolve, and the remaining checks must still
        surface.
        """
        errors: list[str] = []
        prefix = "by_target_period"

        write_strategy = (
            data_flow_definition.write_strategy or FlowUpdateStrategies.OVERWRITE
        ).upper()
        if write_strategy not in BY_TARGET_PERIOD_ALLOWED_WRITE_STRATEGIES:
            errors.append(
                f"{prefix}: write strategy '{write_strategy}' is not supported, "
                f"use one of {', '.join(BY_TARGET_PERIOD_ALLOWED_WRITE_STRATEGIES)} "
                f"({FlowUpdateStrategies.DEL_INS_SCOPED} replaces the periods)"
            )

        masters = resolve_master_predecessors(data_flow_definition.predecessors)
        if not masters:
            errors.append(
                f"{prefix}: the flow needs at least one MASTER predecessor "
                f"holding the '{self.get_source_period_field()}' column"
            )

        if data_flow_definition.target_structure is None:
            errors.append(f"{prefix}: the flow needs a target_structure")
        else:
            try:
                target_structure = data_flow_definition.resolve_target_structure()
            except Exception:
                target_structure = None
            if target_structure is not None and not target_structure.has_field(
                self.period_field,
            ):
                errors.append(
                    f"{prefix}: period_field '{self.period_field}' is not a "
                    f"field of the target structure '{target_structure.name}'"
                )

        for predecessor_name, predecessor in masters:
            try:
                master_structure = predecessor.full_path.resolve(
                    entity_type="structure",
                )
            except Exception:
                continue
            if not master_structure.has_field(self.get_source_period_field()):
                errors.append(
                    f"{prefix}: source period field "
                    f"'{self.get_source_period_field()}' is not a field of the "
                    f"MASTER predecessor '{predecessor_name}'"
                )
            if self.scan_field is not None:
                if not master_structure.has_field(self.scan_field):
                    errors.append(
                        f"{prefix}: scan_field '{self.scan_field}' is not a "
                        f"field of the MASTER predecessor '{predecessor_name}'"
                    )
            elif (
                self.perimeter == PeriodPerimeter.DISCOVERED
                and master_structure.get_last_update_tst_field() is None
            ):
                errors.append(
                    f"{prefix}: the 'discovered' perimeter needs a scan_field "
                    f"or a REC_LAST_UPDATE_TST field on the MASTER predecessor "
                    f"'{predecessor_name}'"
                )
        return errors


PERIODS_PARAM = FlowIncrementalParamDefinition(
    name="periods",
    short_name="periods",
    data_type="list",
    mandatory=False,
    default_value=None,
    help_text="Periods to replace, as period keys (e.g. 2026-07 for MONTH).",
)

PERIOD_FROM_PARAM = FlowIncrementalParamDefinition(
    name="period_from",
    short_name="period_from",
    data_type="str",
    mandatory=False,
    default_value=None,
    help_text="First period of the range to replace (inclusive).",
)

PERIOD_TO_PARAM = FlowIncrementalParamDefinition(
    name="period_to",
    short_name="period_to",
    data_type="str",
    mandatory=False,
    default_value=None,
    help_text="Last period of the range to replace (inclusive).",
)

LIMIT_PARAM = FlowIncrementalParamDefinition(
    name="limit",
    short_name="limit",
    data_type="int",
    mandatory=False,
    default_value=None,
    help_text="Maximum number of periods to replace, oldest first.",
)

BY_TARGET_PERIOD_INCREMENTAL_DEFINITION = FlowIncrementalDefinition(
    default_strategy=FlowLoadingStrategies.DELTA,
    name="BY_TARGET_PERIOD",
    category="by_target_period",
    source_selection=FlowSourceSelection.BY_PERIOD,
    target_update_granularity=FlowTargetUpdateGranularity.BY_PERIOD,
    state_class=ByTargetPeriodState,
    source_state_class=ByTargetPeriodSourceState,
    processing_state_class=ByTargetPeriodProcessingState,
    planned_processing_state_class=ByTargetPeriodPlannedProcessingState,
    planned_processing_detailed_state_class=(
        ByTargetPeriodPlannedProcessingDetailedState
    ),
    auto_processing_state_transition=True,
    partial_state_persistence=False,
    tracks_logical_deletion=False,
    # The type may scan its sources; the state manager narrows it to the
    # strategies whose perimeter actually comes from a scan.
    requires_source_state_retrieval=True,
    supports_planned_state=True,
    allowed_write_strategies=BY_TARGET_PERIOD_ALLOWED_WRITE_STRATEGIES,
    target_scoped=True,
    options_model=ByTargetPeriodOptions,
    param_definitions=[
        FULL_FLAG_PARAM,
        LIMIT_PARAM,
        PERIOD_FROM_PARAM,
        PERIOD_TO_PARAM,
        PERIODS_PARAM,
        WITH_DELTA_FLAG_PARAM,
    ],
)


class ByTargetPeriodFlowIncrementalParams(FlowIncrementalParams):
    """Runtime parameters of a by_target_period run.

    Strategy rules, identical for every perimeter except DELTA:

    - nothing: DELTA, whose periods come from the perimeter (rejected for
      ``declared``, which has no way to find periods on its own);
    - ``--full``: FULL, every period present in the source (source scan)
      and every period already recorded in the state, so a period that
      vanished from the source is emptied;
    - ``--periods`` / ``--period-from [--period-to]``: BACKFILL, exactly
      the declared periods, whatever their state;
    - the same plus ``--with-delta``: BACKFILL_DELTA, the declared periods
      minus those already SUCCEEDED;
    - ``--full`` with ``--with-delta``: rejected.

    ``--limit`` caps any strategy to its N oldest periods.
    """

    _definition: ClassVar[FlowIncrementalDefinition] = (
        BY_TARGET_PERIOD_INCREMENTAL_DEFINITION
    )
    limit: int | None = None
    options: ByTargetPeriodOptions | None = None
    period_from: str | None = None
    period_to: str | None = None
    periods: list[str] | None = None

    @field_validator("periods", mode="before")
    @classmethod
    def parse_periods_from_string(
        cls,
        value: list[str] | str | None,
    ) -> list[str] | None:
        """Convert a comma-separated string into a list of period keys."""
        if isinstance(value, str):
            return [period.strip() for period in value.split(",") if period.strip()]
        return value

    @model_validator(mode="after")
    def normalize_period_parameters(self) -> "ByTargetPeriodFlowIncrementalParams":
        """Validate the period literals against the configured granularity."""
        if self.options is None:
            return self
        calendar = self.options.calendar
        if self.periods is not None:
            self.periods = calendar.sort_keys(
                [calendar.normalize_key(period) for period in self.periods],
            )
        if self.period_from is not None:
            self.period_from = calendar.normalize_key(self.period_from)
        if self.period_to is not None:
            self.period_to = calendar.normalize_key(self.period_to)
        if self.period_from is not None and self.period_to is not None:
            calendar.enumerate_keys(
                from_key=self.period_from,
                to_key=self.period_to,
            )
        return self

    def has_declared_periods(self) -> bool:
        return bool(self.periods) or self.period_from is not None

    def get_declared_periods(self) -> list[str]:
        """Return the declared periods, chronologically and deduplicated.

        ``--period-to`` defaults to ``--period-from``, so a lone
        ``--period-from`` declares a single period.
        """
        assert self.options is not None
        calendar = self.options.calendar
        declared = list(self.periods or [])
        if self.period_from is not None:
            declared.extend(
                calendar.enumerate_keys(
                    from_key=self.period_from,
                    to_key=self.period_to or self.period_from,
                )
            )
        return calendar.sort_keys(declared)

    def resolve_strategy(self) -> str:
        if self.full and self.with_delta:
            raise ValueError(
                "The flags '--full' and '--with-delta' are mutually exclusive. "
                "Please provide only one of them."
            )
        if self.full:
            return FlowLoadingStrategies.FULL
        if self.has_declared_periods() and self.with_delta:
            return FlowLoadingStrategies.BACKFILL_DELTA
        if self.has_declared_periods():
            return FlowLoadingStrategies.BACKFILL
        return FlowLoadingStrategies.DELTA

    @classmethod
    def get_definition(cls) -> FlowIncrementalDefinition:
        return cls._definition

    def is_incremental_parameters_allowed(self) -> tuple[bool, str]:
        if self.options is None:
            return (
                False,
                "Incremental type 'by_target_period' requires the "
                "'incremental.options' block (perimeter, granularity, "
                "period_field).",
            )
        if self.limit is not None and self.limit < 1:
            return (False, "The parameter 'limit' must be greater than 0.")
        if self.period_to is not None and self.period_from is None:
            return (
                False,
                "The parameter 'period_to' requires 'period_from'.",
            )
        if self.strategy == FlowLoadingStrategies.FULL:
            for parameter_name in ("periods", "period_from", "period_to"):
                if getattr(self, parameter_name) is not None:
                    self.log_event(
                        IncrementalParameterIgnored(
                            self.strategy,
                            parameter_name=parameter_name,
                        )
                    )
            return (True, "")
        if (
            self.strategy == FlowLoadingStrategies.DELTA
            and self.options.perimeter == PeriodPerimeter.DECLARED
        ):
            return (
                False,
                "The 'declared' perimeter of 'by_target_period' needs the "
                "periods to process: pass '--periods' or "
                "'--period-from' [and '--period-to'].",
            )
        return (True, "")


BY_TARGET_PERIOD_FLOW_INCREMENTAL_LOGIC = FlowIncrementalLogic[
    ByTargetPeriodFlowIncrementalParams
](
    definition=BY_TARGET_PERIOD_INCREMENTAL_DEFINITION,
    parameter_class=ByTargetPeriodFlowIncrementalParams,
)
