import datetime

from pydantic import Field, PrivateAttr, field_validator

from nld.flow.incremental.models import (
    FlowPlannedProcessingDetailedState,
    FlowPlannedProcessingState,
    FlowProcessingState,
    FlowSourceState,
    FlowState,
    IncrementalProcessingStatus,
    IncrementalStateStatus,
)
from nld.pydantic import NldBaseModel
from nld.utils.datetime_util import ensure_utc_datetime, get_current_datetime
from nld.utils.user_display import (
    format_datetime_for_display,
    format_key_value_lines,
)

PERIODS_SAMPLE_SIZE = 10


def render_period_entries(
    entries: list[tuple[str, str]],
) -> list[str]:
    """Render per-status period counts plus the first and last periods.

    ``entries`` is a ``(period_key, status)`` list; keys sort
    chronologically, so the sample shows the oldest periods first.
    """
    counts: dict[str, int] = {}
    for _, status in entries:
        label = status or "N/A"
        counts[label] = counts.get(label, 0) + 1
    pairs: list[tuple[str, str]] = [("Periods total", str(len(entries)))]
    for status, count in sorted(counts.items()):
        pairs.append((status, str(count)))
    lines = format_key_value_lines(pairs=pairs)
    sorted_entries = sorted(entries)
    sample = sorted_entries[:PERIODS_SAMPLE_SIZE]
    if sample:
        header = (
            f"  Periods ({len(sample)} of {len(sorted_entries)}):"
            if len(sorted_entries) > len(sample)
            else f"  Periods ({len(sample)}):"
        )
        lines.append(header)
        lines.extend(f"    - {name} ({status})" for name, status in sample)
    return lines


class ByTargetPeriodSinglePeriodState(NldBaseModel):
    """Authoritative state of one period of the target."""

    first_processed_at: datetime.datetime | None = None
    last_process_error_message: str | None = None
    last_process_status: str = IncrementalStateStatus.NOT_PROCESSED
    last_processed_at: datetime.datetime | None = None
    # Latest source modification seen for this period by a scan; empty
    # for periods only ever selected from runtime parameters.
    last_source_modified_at: datetime.datetime | None = None
    last_successfully_processed_at: datetime.datetime | None = None
    name: str
    status: str = IncrementalStateStatus.NOT_PROCESSED

    @field_validator(
        "last_successfully_processed_at",
        "last_processed_at",
        "first_processed_at",
        "last_source_modified_at",
        mode="after",
    )
    @classmethod
    def validate_utc_timezone(
        cls,
        value: datetime.datetime | None,
    ) -> datetime.datetime | None:
        """Enforce UTC timezone on all timestamp fields."""
        return ensure_utc_datetime(value)

    def succeeded(self) -> bool:
        return self.status == IncrementalStateStatus.SUCCEEDED

    def failed(self) -> bool:
        return self.status == IncrementalStateStatus.FAILED

    def not_processed(self) -> bool:
        return self.status == IncrementalStateStatus.NOT_PROCESSED

    def pending(self) -> bool:
        """True when the period still waits for a successful replacement.

        Covers the failed periods and the periods discovered as modified
        but excluded from their run (e.g. by ``--limit``).
        """
        return self.failed() or self.not_processed()


class ByTargetPeriodState(FlowState):
    """Authoritative by_target_period state: one entry per period ever seen.

    ``granularity``, ``period_timezone`` and ``week_start`` are persisted
    because they give every period key its meaning: a flow whose calendar
    changes must not silently merge keys of another calendar.
    ``last_scan_at`` is the source scan watermark; it stays None until a
    scan-based run succeeds.
    """

    granularity: str | None = None
    last_scan_at: datetime.datetime | None = None
    period_timezone: str | None = None
    periods: dict[str, ByTargetPeriodSinglePeriodState] = Field(default_factory=dict)
    week_start: str | None = None
    # Periods modified since ``start_tracking_changes``; None when not
    # tracking, in which case every period counts as changed.
    _changed_periods: set[str] | None = PrivateAttr(default=None)

    @field_validator(
        "last_scan_at",
        mode="after",
    )
    @classmethod
    def validate_utc_timezone(
        cls,
        value: datetime.datetime | None,
    ) -> datetime.datetime | None:
        """Enforce UTC timezone on all timestamp fields."""
        return ensure_utc_datetime(value)

    def has_period(self, name: str) -> bool:
        return name in self.periods

    def start_tracking_changes(self) -> None:
        """Record from now on which periods are modified.

        Lets row-per-period backends rewrite only the periods a run touched
        instead of the whole history, which grows with every period seen.
        """
        self._changed_periods = set()

    def mark_period_changed(self, name: str) -> None:
        if self._changed_periods is not None:
            self._changed_periods.add(name)

    def get_changed_periods(self) -> list[ByTargetPeriodSinglePeriodState]:
        """Return the periods to persist: the tracked changes, else all."""
        if self._changed_periods is None:
            return list(self.periods.values())
        return [
            self.periods[name]
            for name in sorted(self._changed_periods)
            if name in self.periods
        ]

    def get_succeeded_periods(self) -> list[str]:
        return sorted(name for name, state in self.periods.items() if state.succeeded())

    def get_pending_periods(self) -> list[str]:
        return sorted(name for name, state in self.periods.items() if state.pending())

    def render_state_text(self) -> str:
        """Render the calendar, the scan watermark and the period counts."""
        pairs: list[tuple[str, str]] = []
        if self.granularity is not None:
            pairs.append(("Granularity", self.granularity))
        if self.period_timezone is not None:
            pairs.append(("Timezone", self.period_timezone))
        if self.week_start is not None:
            pairs.append(("Week start", self.week_start))
        if self.last_scan_at is not None:
            pairs.append(
                (
                    "Last scan at",
                    format_datetime_for_display(value=self.last_scan_at),
                )
            )
        lines = format_key_value_lines(pairs=pairs)
        lines.extend(
            render_period_entries(
                entries=[(name, state.status) for name, state in self.periods.items()],
            )
        )
        return "\n".join(lines)


class ByTargetPeriodSinglePeriodSourceState(NldBaseModel):
    """One period reported by a source scan."""

    last_source_modified_at: datetime.datetime | None = None
    name: str

    @field_validator(
        "last_source_modified_at",
        mode="after",
    )
    @classmethod
    def validate_utc_timezone(
        cls,
        value: datetime.datetime | None,
    ) -> datetime.datetime | None:
        """Enforce UTC timezone on all timestamp fields."""
        return ensure_utc_datetime(value)


class ByTargetPeriodSourceState(FlowSourceState):
    """Periods modified in the source since the scan lower bound.

    ``scanned_at`` is captured before the scan query runs, so rows written
    while it runs are picked up by the next scan instead of being skipped.
    """

    periods: dict[str, ByTargetPeriodSinglePeriodSourceState] = Field(
        default_factory=dict,
    )
    scanned_at: datetime.datetime

    @field_validator(
        "scanned_at",
        mode="after",
    )
    @classmethod
    def validate_utc_timezone(
        cls,
        value: datetime.datetime,
    ) -> datetime.datetime:
        """Enforce UTC timezone on all timestamp fields."""
        return ensure_utc_datetime(value)  # type: ignore[return-value]


class ByTargetPeriodSinglePeriodProcessingState(NldBaseModel):
    """Outcome of one period within a run."""

    last_source_modified_at: datetime.datetime | None = None
    name: str
    process_error_message: str | None = None
    processing_completed_at: datetime.datetime | None = None
    processing_status: str = IncrementalProcessingStatus.TO_BE_PROCESSED

    @field_validator(
        "processing_completed_at",
        "last_source_modified_at",
        mode="after",
    )
    @classmethod
    def validate_utc_timezone(
        cls,
        value: datetime.datetime | None,
    ) -> datetime.datetime | None:
        """Enforce UTC timezone on all timestamp fields."""
        return ensure_utc_datetime(value)

    def to_be_processed(self) -> bool:
        return self.processing_status == IncrementalProcessingStatus.TO_BE_PROCESSED

    def excluded(self) -> bool:
        return self.processing_status == IncrementalProcessingStatus.EXCLUDED

    def succeeded(self) -> bool:
        return self.processing_status == IncrementalProcessingStatus.SUCCEEDED

    def failed(self) -> bool:
        return self.processing_status == IncrementalProcessingStatus.FAILED


class ByTargetPeriodProcessingState(FlowProcessingState):
    """The periods one run replaces, and the outcome of the run.

    A run is processed as a whole: one filtered query covers every period
    to process, so ``set_to_succeeded`` and ``set_to_failed`` fan the run
    outcome out to every period still to be processed. The run-level
    status also records the outcome of a run with no period at all.
    """

    granularity: str
    period_timezone: str = "UTC"
    periods: dict[str, ByTargetPeriodSinglePeriodProcessingState] = Field(
        default_factory=dict,
    )
    process_error_message: str | None = None
    processing_completed_at: datetime.datetime | None = None
    processing_status: str = IncrementalProcessingStatus.TO_BE_PROCESSED
    # Set when the perimeter came from a source scan; the scan watermark
    # advances to it once the run succeeds.
    scanned_at: datetime.datetime | None = None
    week_start: str | None = None

    @field_validator(
        "scanned_at",
        "processing_completed_at",
        mode="after",
    )
    @classmethod
    def validate_utc_timezone(
        cls,
        value: datetime.datetime | None,
    ) -> datetime.datetime | None:
        """Enforce UTC timezone on all timestamp fields."""
        return ensure_utc_datetime(value)

    def add_period(
        self,
        name: str,
        processing_status: str = IncrementalProcessingStatus.TO_BE_PROCESSED,
        last_source_modified_at: datetime.datetime | None = None,
    ) -> None:
        """Add or replace the processing entry of one period."""
        self.periods[name] = ByTargetPeriodSinglePeriodProcessingState(
            name=name,
            processing_status=processing_status,
            last_source_modified_at=last_source_modified_at,
        )

    def get_periods_to_process(self) -> list[str]:
        """Return the keys of the periods this run replaces, oldest first."""
        return sorted(
            name for name, state in self.periods.items() if state.to_be_processed()
        )

    def get_excluded_periods(self) -> list[str]:
        return sorted(name for name, state in self.periods.items() if state.excluded())

    def set_to_succeeded(self) -> None:
        completed_at = get_current_datetime()
        self.processing_status = IncrementalProcessingStatus.SUCCEEDED
        self.process_error_message = None
        self.processing_completed_at = completed_at
        for period in self.periods.values():
            if period.to_be_processed():
                period.processing_status = IncrementalProcessingStatus.SUCCEEDED
                period.process_error_message = None
                period.processing_completed_at = completed_at

    def set_to_failed(self, error_message: str | None = None) -> None:
        completed_at = get_current_datetime()
        self.processing_status = IncrementalProcessingStatus.FAILED
        self.process_error_message = error_message
        self.processing_completed_at = completed_at
        for period in self.periods.values():
            if period.to_be_processed():
                period.processing_status = IncrementalProcessingStatus.FAILED
                period.process_error_message = error_message
                period.processing_completed_at = completed_at

    def succeeded(self) -> bool:
        return self.processing_status == IncrementalProcessingStatus.SUCCEEDED

    def failed(self) -> bool:
        return self.processing_status == IncrementalProcessingStatus.FAILED

    def get_display_log(self) -> str:
        """Return a human-readable summary of the processing state."""
        periods_to_process = self.get_periods_to_process()
        if not periods_to_process:
            range_display = "none"
        elif len(periods_to_process) == 1:
            range_display = periods_to_process[0]
        else:
            range_display = f"{periods_to_process[0]} → {periods_to_process[-1]}"
        return (
            f"Strategy: {self.strategy} | Granularity: {self.granularity} | "
            f"Periods to process: {len(periods_to_process)} [{range_display}]"
        )

    def render_state_text(self) -> str:
        """Render the run outcome and the per-period statuses."""
        pairs: list[tuple[str, str]] = [
            ("Granularity", self.granularity),
            ("Timezone", self.period_timezone),
            ("Status", str(self.processing_status)),
        ]
        if self.week_start is not None:
            pairs.insert(2, ("Week start", self.week_start))
        if self.scanned_at is not None:
            pairs.append(
                (
                    "Scanned at",
                    format_datetime_for_display(value=self.scanned_at),
                )
            )
        if self.processing_completed_at is not None:
            pairs.append(
                (
                    "Completed at",
                    format_datetime_for_display(value=self.processing_completed_at),
                )
            )
        if self.process_error_message is not None:
            pairs.append(("Error", str(self.process_error_message)))
        lines = format_key_value_lines(pairs=pairs)
        lines.extend(
            render_period_entries(
                entries=[
                    (name, state.processing_status)
                    for name, state in self.periods.items()
                ],
            )
        )
        return "\n".join(lines)


class ByTargetPeriodSinglePeriodPlannedProcessingDetailedState(NldBaseModel):
    """One period of a PLANNED plan."""

    last_source_modified_at: datetime.datetime | None = None
    name: str
    planned_processing_status: str = IncrementalProcessingStatus.TO_BE_PROCESSED

    @field_validator(
        "last_source_modified_at",
        mode="after",
    )
    @classmethod
    def validate_utc_timezone(
        cls,
        value: datetime.datetime | None,
    ) -> datetime.datetime | None:
        """Enforce UTC timezone on all timestamp fields."""
        return ensure_utc_datetime(value)


class ByTargetPeriodPlannedProcessingDetailedState(
    FlowPlannedProcessingDetailedState[ByTargetPeriodProcessingState],
):
    """Plan-time detail for a by_target_period PLANNED plan."""

    granularity: str
    period_timezone: str = "UTC"
    periods: dict[str, ByTargetPeriodSinglePeriodPlannedProcessingDetailedState] = (
        Field(default_factory=dict)
    )
    scanned_at: datetime.datetime | None = None
    strategy: str
    week_start: str | None = None

    @field_validator(
        "scanned_at",
        mode="after",
    )
    @classmethod
    def validate_utc_timezone(
        cls,
        value: datetime.datetime | None,
    ) -> datetime.datetime | None:
        """Enforce UTC timezone on all timestamp fields."""
        return ensure_utc_datetime(value)

    def to_processing_state(self, flow_uid: str) -> ByTargetPeriodProcessingState:
        return ByTargetPeriodProcessingState(
            flow_uid=flow_uid,
            strategy=self.strategy,
            granularity=self.granularity,
            period_timezone=self.period_timezone,
            week_start=self.week_start,
            scanned_at=self.scanned_at,
            periods={
                name: ByTargetPeriodSinglePeriodProcessingState(
                    name=period.name,
                    processing_status=period.planned_processing_status,
                    last_source_modified_at=period.last_source_modified_at,
                )
                for name, period in self.periods.items()
            },
        )

    @classmethod
    def from_processing_state(
        cls,
        plan_state_uid: str,
        processing_state: ByTargetPeriodProcessingState,
    ) -> "ByTargetPeriodPlannedProcessingDetailedState":
        return cls(
            plan_state_uid=plan_state_uid,
            strategy=processing_state.strategy,
            granularity=processing_state.granularity,
            period_timezone=processing_state.period_timezone,
            week_start=processing_state.week_start,
            scanned_at=processing_state.scanned_at,
            periods={
                name: ByTargetPeriodSinglePeriodPlannedProcessingDetailedState(
                    name=period.name,
                    planned_processing_status=period.processing_status,
                    last_source_modified_at=period.last_source_modified_at,
                )
                for name, period in processing_state.periods.items()
            },
        )


class ByTargetPeriodPlannedProcessingState(
    FlowPlannedProcessingState[ByTargetPeriodPlannedProcessingDetailedState],
):
    """A PLANNED plan carrying a by_target_period planned-detail payload."""
