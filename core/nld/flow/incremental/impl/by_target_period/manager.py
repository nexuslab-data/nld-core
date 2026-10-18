import datetime
from typing import Any

import sqlglot
from sqlglot import exp

from nld.connector.base.connector import DataConnector, SQLDataConnector
from nld.flow.definition.flow_definition import (
    DataFlowStructurePredecessor,
)
from nld.flow.incremental.base.manager import (
    IncrementalBackendStateManager,
    IncrementalStateManager,
)
from nld.flow.incremental.base.sql_filter_manager import IncrementalSqlFilterManager
from nld.flow.incremental.impl.by_target_period.logic import (
    BY_TARGET_PERIOD_FLOW_INCREMENTAL_LOGIC,
    ByTargetPeriodFlowIncrementalParams,
    ByTargetPeriodOptions,
    PeriodPerimeter,
)
from nld.flow.incremental.impl.by_target_period.period import resolve_week_start
from nld.flow.incremental.impl.by_target_period.sql_builder import (
    build_period_condition,
    build_period_scan_query,
    resolve_column_kind,
)
from nld.flow.incremental.impl.by_target_period.sql_filter_manager import (
    ByTargetPeriodSqlFilterManager,
    resolve_master_table_references,
)
from nld.flow.incremental.impl.by_target_period.state import (
    ByTargetPeriodPlannedProcessingDetailedState,
    ByTargetPeriodPlannedProcessingState,
    ByTargetPeriodProcessingState,
    ByTargetPeriodSinglePeriodSourceState,
    ByTargetPeriodSinglePeriodState,
    ByTargetPeriodSourceState,
    ByTargetPeriodState,
)
from nld.flow.incremental.models import (
    IncrementalProcessingStatus,
    IncrementalStateStatus,
)
from nld.flow.utils import FlowLoadingStrategies
from nld.structure import Structure
from nld.utils.datetime_util import get_current_datetime, normalize_to_utc


class ByTargetPeriodStateManager(
    IncrementalStateManager[
        ByTargetPeriodState,
        ByTargetPeriodSourceState,
        ByTargetPeriodProcessingState,
        ByTargetPeriodPlannedProcessingState,
        ByTargetPeriodFlowIncrementalParams,
    ]
):
    """State manager of the by_target_period incremental type.

    A run replaces a set of calendar periods of the target. The perimeter
    of a DELTA run comes from the flow options: the runtime parameters
    (``declared``), a scan of the source for the periods modified since the
    last scan (``discovered``) or a window of the last periods
    (``rolling``). Every DELTA also retries the periods still pending from
    earlier runs (failed, or discovered but not processed yet).
    """

    flow_incremental_logic = BY_TARGET_PERIOD_FLOW_INCREMENTAL_LOGIC

    def __init__(
        self,
        incremental_parameters: ByTargetPeriodFlowIncrementalParams,
        incremental_state_backend_manager: IncrementalBackendStateManager[
            DataConnector[Any],
            ByTargetPeriodState,
            ByTargetPeriodSourceState,
            ByTargetPeriodProcessingState,
            ByTargetPeriodPlannedProcessingState,
            ByTargetPeriodPlannedProcessingDetailedState,
        ]
        | None = None,
        secondary_incremental_state_backend_manager: IncrementalBackendStateManager[
            DataConnector[Any],
            ByTargetPeriodState,
            ByTargetPeriodSourceState,
            ByTargetPeriodProcessingState,
            ByTargetPeriodPlannedProcessingState,
            ByTargetPeriodPlannedProcessingDetailedState,
        ]
        | None = None,
        parameters: dict[str, Any] | None = None,
    ):
        super().__init__(
            incremental_parameters=incremental_parameters,
            incremental_state_backend_manager=incremental_state_backend_manager,
            secondary_incremental_state_backend_manager=(
                secondary_incremental_state_backend_manager
            ),
            parameters=parameters,
        )
        self.processing_state: ByTargetPeriodProcessingState

    @property
    def options(self) -> ByTargetPeriodOptions:
        """Return the validated flow options (checked at construction)."""
        assert self.incremental_parameters.options is not None
        return self.incremental_parameters.options

    # Source scan

    def requires_source_state_retrieval(self) -> bool:
        """Scan the source only when the run's perimeter comes from a scan.

        FULL always scans (every period present in the source, plus the
        periods already recorded in the state), DELTA scans
        for the ``discovered`` perimeter only, and declared replays never
        scan.
        """
        if self.strategy == FlowLoadingStrategies.FULL:
            return True
        return (
            self.strategy == FlowLoadingStrategies.DELTA
            and self.options.perimeter == PeriodPerimeter.DISCOVERED
        )

    def retrieve_source_state_from_sql(
        self,
        sql_query: str,
        predecessors: dict[str, DataFlowStructurePredecessor],
        connector: SQLDataConnector[Any],
        input_database_names: dict[str, str] | None = None,
    ) -> None:
        """Scan every MASTER predecessor for the periods modified recently.

        FULL scans without lower bound; DELTA scans from the watermark of
        the last successful scan. Periods found in several MASTER
        predecessors are unioned, keeping their latest modification.

        Raises:
            RuntimeError: if a scan query fails.
            ValueError: if a MASTER predecessor cannot be scanned.
        """
        dialect = getattr(connector, "sqlglot_dialect", None) or "postgres"
        scanned_at = get_current_datetime()
        scanned_from = (
            None
            if self.strategy == FlowLoadingStrategies.FULL
            or self.latest_incremental_state is None
            else self.latest_incremental_state.last_scan_at
        )
        calendar = self.options.calendar
        parsed_query = sqlglot.parse_one(
            sql_query,
            dialect=dialect,
        )
        modified_periods: dict[str, datetime.datetime | None] = {}

        for (
            predecessor_name,
            master_structure,
            table_nodes,
        ) in resolve_master_table_references(
            parsed=parsed_query,
            predecessors=predecessors,
            input_database_names=input_database_names,
        ):
            source_period_field_name = self.options.get_source_period_field()
            # A full scan lists every day of the source, so it can do
            # without a modification column; a bounded scan cannot.
            scan_field_name = self._resolve_scan_field_name(
                predecessor_name=predecessor_name,
                master_structure=master_structure,
                is_required=scanned_from is not None,
            )
            scan_query = build_period_scan_query(
                # Every read of a MASTER is the same table: scan it once.
                table=table_nodes[0],
                period_field_name=source_period_field_name,
                period_column_kind=resolve_column_kind(
                    field=master_structure.get_field(source_period_field_name),
                    dialect=dialect,
                ),
                scan_field_name=scan_field_name,
                scan_column_kind=(
                    None
                    if scan_field_name is None
                    else resolve_column_kind(
                        field=master_structure.get_field(scan_field_name),
                        dialect=dialect,
                    )
                ),
                timezone=self.options.period_timezone,
                scanned_from=scanned_from,
                dialect=dialect,
            )
            query_result = connector.execute_query(scan_query)
            if query_result.failed():
                raise RuntimeError(
                    f"Source scan of '{master_structure.name}' failed: "
                    f"{query_result.get_error_message()}"
                )
            for record in query_result.get_result_records():
                period_name = calendar.format_key(
                    self._to_date(value=record["period_day"]),
                )
                last_modified_at = normalize_to_utc(record["last_source_modified_at"])
                known_modified_at = modified_periods.get(period_name)
                if known_modified_at is None or (
                    last_modified_at is not None
                    and last_modified_at > known_modified_at
                ):
                    modified_periods[period_name] = last_modified_at

        self.log_info(
            f"Source scan found {len(modified_periods)} modified period(s)"
            + (f" since {scanned_from.isoformat()}" if scanned_from else ""),
        )
        self.set_source_state(
            ByTargetPeriodSourceState(
                periods={
                    name: ByTargetPeriodSinglePeriodSourceState(
                        name=name,
                        last_source_modified_at=last_modified_at,
                    )
                    for name, last_modified_at in modified_periods.items()
                },
                scanned_at=scanned_at,
            )
        )

    def _resolve_scan_field_name(
        self,
        predecessor_name: str,
        master_structure: Structure,
        is_required: bool = True,
    ) -> str | None:
        """Return the modification column scanned on a MASTER predecessor.

        Raises:
            ValueError: if the column is required and cannot be resolved.
        """
        if self.options.scan_field is not None:
            return self.options.scan_field
        last_update_field = master_structure.get_last_update_tst_field()
        if last_update_field is None:
            if not is_required:
                return None
            raise ValueError(
                f"by_target_period cannot scan the MASTER predecessor "
                f"'{predecessor_name}': set the 'scan_field' option or "
                f"characterise a field of '{master_structure.name}' as "
                f"REC_LAST_UPDATE_TST."
            )
        return last_update_field.name

    @staticmethod
    def _to_date(value: Any) -> datetime.date:
        """Coerce a scanned day returned by a driver into a date."""
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, datetime.date):
            return value
        return datetime.date.fromisoformat(str(value)[:10])

    # Processing state

    def init_processing_state(self) -> None:
        self.processing_state = ByTargetPeriodProcessingState(
            flow_uid=self.flow_uid,
            strategy=self.strategy,
            granularity=self.options.granularity,
            period_timezone=self.options.period_timezone,
            week_start=self.options.get_week_start(),
        )

    def update_processing_state(self) -> None:
        """Select the periods this run replaces, oldest first.

        Raises:
            ValueError: if the persisted state was built with another
                calendar, or if the selection exceeds max_periods_per_run.
            RuntimeError: if a scan-based perimeter has no source state.
        """
        self._check_state_calendar()
        candidates: dict[str, datetime.datetime | None] = {}
        excluded: list[str] = []

        if self.strategy == FlowLoadingStrategies.FULL:
            candidates.update(self._get_scanned_periods())
            # Periods written by earlier runs are replaced too, so a period
            # that vanished from the source is emptied instead of kept stale.
            for name in self._get_latest_state().periods:
                candidates.setdefault(name, None)
        elif self.strategy == FlowLoadingStrategies.DELTA:
            candidates.update(self._get_delta_perimeter())
        elif self.strategy == FlowLoadingStrategies.BACKFILL:
            candidates.update(
                {
                    name: None
                    for name in self.incremental_parameters.get_declared_periods()
                }
            )
        elif self.strategy == FlowLoadingStrategies.BACKFILL_DELTA:
            succeeded = set(self._get_latest_state().get_succeeded_periods())
            for name in self.incremental_parameters.get_declared_periods():
                if name in succeeded:
                    excluded.append(name)
                else:
                    candidates[name] = None
        else:
            raise NotImplementedError(
                f"The method 'update_processing_state' is not implemented "
                f"for data load strategy {self.strategy}"
            )

        calendar = self.options.calendar
        ordered = calendar.sort_keys(list(candidates))
        limit = self.incremental_parameters.limit
        selected = ordered if limit is None else ordered[:limit]
        selected_names = set(selected)
        for name in ordered:
            self.processing_state.add_period(
                name=name,
                processing_status=(
                    IncrementalProcessingStatus.TO_BE_PROCESSED
                    if name in selected_names
                    else IncrementalProcessingStatus.EXCLUDED
                ),
                last_source_modified_at=candidates[name],
            )
        for name in excluded:
            self.processing_state.add_period(
                name=name,
                processing_status=IncrementalProcessingStatus.EXCLUDED,
            )

        max_periods = self.options.max_periods_per_run
        if max_periods is not None and len(selected) > max_periods:
            raise ValueError(
                f"The run selects {len(selected)} periods "
                f"({selected[0]} → {selected[-1]}), more than "
                f"max_periods_per_run={max_periods}: pass '--limit' to "
                f"process them in several runs, oldest first."
            )

    def _get_delta_perimeter(self) -> dict[str, datetime.datetime | None]:
        """Return the DELTA periods: the perimeter plus the pending periods."""
        perimeter: dict[str, datetime.datetime | None] = {}
        if self.options.perimeter == PeriodPerimeter.DISCOVERED:
            perimeter.update(self._get_scanned_periods())
        elif self.options.perimeter == PeriodPerimeter.ROLLING:
            perimeter.update(
                {
                    name: None
                    for name in self.options.calendar.get_rolling_keys(
                        moment=get_current_datetime(),
                        lookback_periods=self.options.get_lookback_periods(),
                        include_current_period=bool(
                            self.options.include_current_period,
                        ),
                    )
                }
            )
        latest_state = self._get_latest_state()
        for name in latest_state.get_pending_periods():
            if name not in perimeter:
                perimeter[name] = latest_state.periods[name].last_source_modified_at
        return perimeter

    def _get_scanned_periods(self) -> dict[str, datetime.datetime | None]:
        """Return the periods of the source scan and record its timestamp."""
        if self.source_state is None:
            raise RuntimeError(
                f"Strategy {self.strategy} of by_target_period needs a scan of "
                f"the source, which only SQL flow tasks provide."
            )
        self.processing_state.scanned_at = self.source_state.scanned_at
        return {
            name: period.last_source_modified_at
            for name, period in self.source_state.periods.items()
        }

    def _get_latest_state(self) -> ByTargetPeriodState:
        if self.latest_incremental_state is None:
            return ByTargetPeriodState()
        return self.latest_incremental_state

    def _check_state_calendar(self) -> None:
        """Refuse a persisted state whose period keys mean something else.

        Raises:
            ValueError: if the granularity, the timezone or the week start
                changed.
        """
        latest_state = self._get_latest_state()
        persisted_week_start = (
            None
            if latest_state.granularity is None
            else resolve_week_start(
                latest_state.granularity,
                week_start=latest_state.week_start,
            )
        )
        for label, persisted, configured in (
            ("granularity", latest_state.granularity, self.options.granularity),
            (
                "period_timezone",
                latest_state.period_timezone,
                self.options.period_timezone,
            ),
            ("week_start", persisted_week_start, self.options.get_week_start()),
        ):
            if persisted is not None and persisted != configured:
                raise ValueError(
                    f"The by_target_period state of this flow was built with "
                    f"{label} '{persisted}' but the flow now declares "
                    f"'{configured}'. Period keys of both calendars cannot be "
                    f"merged: clear the flow's by_target_period state in the "
                    f"state backend, then rerun with '--full' to rebuild it."
                )

    def _is_flow_calendar(
        self,
        detailed_state: ByTargetPeriodPlannedProcessingDetailedState,
    ) -> bool:
        """Whether a plan was computed with the calendar the flow declares."""
        return (
            detailed_state.granularity == self.options.granularity
            and detailed_state.period_timezone == self.options.period_timezone
            and resolve_week_start(
                detailed_state.granularity,
                week_start=detailed_state.week_start,
            )
            == self.options.get_week_start()
        )

    def has_nothing_to_process(self) -> bool:
        """Whether the run selects no period, in which case nothing is written."""
        return (
            self.processing_state is not None
            and not self.processing_state.get_periods_to_process()
        )

    # Planned state

    def use_planned_processing_state(
        self,
        planned_processing_state: ByTargetPeriodPlannedProcessingState,
    ) -> None:
        """Adopt a plan only if its calendar is the flow's calendar.

        Raises:
            ValueError: if the plan was computed with another granularity,
                timezone or week start, whatever the planned-state policy
                (TRUST included), since its period keys would be misread.
        """
        detailed_state = planned_processing_state.detailed_state
        if not self._is_flow_calendar(detailed_state):
            raise ValueError(
                f"Plan '{planned_processing_state.plan_state_uid}' was computed "
                f"for granularity '{detailed_state.granularity}', timezone "
                f"'{detailed_state.period_timezone}' and week start "
                f"'{detailed_state.week_start}', the flow now declares "
                f"'{self.options.granularity}', "
                f"'{self.options.period_timezone}' and "
                f"'{self.options.get_week_start()}': recompute the plan."
            )
        self._check_state_calendar()
        super().use_planned_processing_state(
            planned_processing_state=planned_processing_state,
        )

    def is_planned_processing_state_fresh(
        self,
        planned_processing_state: ByTargetPeriodPlannedProcessingState,
    ) -> bool:
        """Whether a plan still matches the flow calendar and the scan watermark.

        A plan built with another calendar is stale. A scan-based plan is
        stale once a later run moved the scan watermark past the plan's
        own scan, since that run already consumed what the plan found.
        """
        detailed_state = planned_processing_state.detailed_state
        if not self._is_flow_calendar(detailed_state):
            return False
        if detailed_state.scanned_at is None or self.latest_incremental_state is None:
            return True
        last_scan_at = self.latest_incremental_state.last_scan_at
        return last_scan_at is None or last_scan_at <= detailed_state.scanned_at

    # SQL integration

    @property
    def sql_filter_manager(self) -> IncrementalSqlFilterManager:
        """Return the period-based SQL filter."""
        return ByTargetPeriodSqlFilterManager(
            processing_state=self.processing_state,
            options=self.options,
        )

    def get_target_scope_condition(
        self,
        target_structure: Structure | None,
        dialect: str,
    ) -> exp.Expression | None:
        """Return the condition selecting the target rows of the run's periods."""
        if target_structure is None:
            return None
        return build_period_condition(
            column=exp.column(self.options.period_field),
            ranges=self.options.calendar.group_contiguous_ranges(
                self.processing_state.get_periods_to_process(),
            ),
            column_kind=resolve_column_kind(
                field=target_structure.get_field(self.options.period_field),
                dialect=dialect,
            ),
            timezone=self.options.period_timezone,
        )

    # Post-processing state

    def create_post_processing_state(self) -> ByTargetPeriodState:
        """Merge the run outcome into the authoritative period state.

        A processed period records its outcome; a failed one becomes FAILED
        even if it succeeded before, since its replacement may have stopped
        between the delete and the insert. A discovered period left out of
        the run by ``--limit`` becomes NOT_PROCESSED so the next DELTA
        retries it. The scan watermark advances only after a successful run
        whose perimeter came from a scan.
        """
        self.post_processing_state = ByTargetPeriodState.deep_copy(
            self._get_latest_state(),
        )
        self.post_processing_state.granularity = self.options.granularity
        self.post_processing_state.period_timezone = self.options.period_timezone
        self.post_processing_state.week_start = self.options.get_week_start()
        self.post_processing_state.start_tracking_changes()

        # Only a DELTA or FULL perimeter leaves work behind when a period is
        # excluded: BACKFILL exclusions are explicit operator choices.
        excluded_periods_stay_pending = self.processing_state.strategy in [
            FlowLoadingStrategies.DELTA,
            FlowLoadingStrategies.FULL,
        ]
        for name, period in self.processing_state.periods.items():
            if period.succeeded() or period.failed():
                self._record_period_outcome(name=name)
            elif period.excluded() and excluded_periods_stay_pending:
                self._record_pending_period(name=name)

        if (
            self.processing_state.succeeded()
            and self.processing_state.scanned_at is not None
        ):
            self.post_processing_state.last_scan_at = self.processing_state.scanned_at

        return self.post_processing_state

    def _get_or_create_period_state(
        self,
        name: str,
    ) -> ByTargetPeriodSinglePeriodState:
        assert self.post_processing_state is not None
        if not self.post_processing_state.has_period(name):
            self.post_processing_state.periods[name] = ByTargetPeriodSinglePeriodState(
                name=name,
            )
        self.post_processing_state.mark_period_changed(name)
        return self.post_processing_state.periods[name]

    def _record_period_outcome(self, name: str) -> None:
        """Record the SUCCEEDED or FAILED outcome of a processed period."""
        period = self.processing_state.periods[name]
        state = self._get_or_create_period_state(name=name)
        completed_at = period.processing_completed_at
        if state.first_processed_at is None:
            state.first_processed_at = completed_at
        state.last_processed_at = completed_at
        if period.last_source_modified_at is not None:
            state.last_source_modified_at = period.last_source_modified_at
        if period.succeeded():
            state.status = IncrementalStateStatus.SUCCEEDED
            state.last_process_status = IncrementalStateStatus.SUCCEEDED
            state.last_successfully_processed_at = completed_at
            state.last_process_error_message = None
        else:
            state.status = IncrementalStateStatus.FAILED
            state.last_process_status = IncrementalStateStatus.FAILED
            state.last_process_error_message = period.process_error_message

    def _record_pending_period(self, name: str) -> None:
        """Mark a discovered but unprocessed period as waiting for a run."""
        period = self.processing_state.periods[name]
        state = self._get_or_create_period_state(name=name)
        if not state.failed():
            state.status = IncrementalStateStatus.NOT_PROCESSED
        if period.last_source_modified_at is not None:
            state.last_source_modified_at = period.last_source_modified_at
