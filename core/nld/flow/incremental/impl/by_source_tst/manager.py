from typing import Any, cast

from nld.connector.base.connector import DataConnector
from nld.flow.incremental.base.manager import (
    IncrementalBackendStateManager,
    IncrementalStateManager,
)
from nld.flow.incremental.base.sql_filter_manager import IncrementalSqlFilterManager
from nld.flow.incremental.impl.by_source_tst.sql_filter_manager import (
    BySourceTstSqlFilterManager,
)
from nld.flow.utils import FlowLoadingStrategies
from nld.utils.datetime_util import get_current_datetime

from .logic import (
    BY_SOURCE_TST_FLOW_INCREMENTAL_LOGIC,
    BySourceTstFlowIncrementalParams,
)
from .state import (
    BySourceTstPlannedProcessingDetailledState,
    BySourceTstPlannedProcessingState,
    BySourceTstProcessingState,
    BySourceTstSourceState,
    BySourceTstState,
)


class BySourceTstStateManager(
    IncrementalStateManager[
        BySourceTstState,
        BySourceTstSourceState,
        BySourceTstProcessingState,
        BySourceTstPlannedProcessingState,
        BySourceTstFlowIncrementalParams,
    ]
):
    flow_incremental_logic = BY_SOURCE_TST_FLOW_INCREMENTAL_LOGIC

    def __init__(
        self,
        incremental_parameters: BySourceTstFlowIncrementalParams,
        incremental_state_backend_manager: IncrementalBackendStateManager[
            DataConnector[Any],
            BySourceTstState,
            BySourceTstSourceState,
            BySourceTstProcessingState,
            BySourceTstPlannedProcessingState,
            BySourceTstPlannedProcessingDetailledState,
        ]
        | None = None,
        secondary_incremental_state_backend_manager: IncrementalBackendStateManager[
            DataConnector[Any],
            BySourceTstState,
            BySourceTstSourceState,
            BySourceTstProcessingState,
            BySourceTstPlannedProcessingState,
            BySourceTstPlannedProcessingDetailledState,
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
        self.processing_state: BySourceTstProcessingState

    def init_processing_state(self) -> None:
        self.processing_state = BySourceTstProcessingState(
            flow_uid=self.flow_uid,
            strategy=self.strategy,
        )

    def update_processing_state(self) -> None:
        assert self.latest_incremental_state is not None

        if self.strategy in [FlowLoadingStrategies.DELTA]:
            self.processing_state.pull_from_timestamp = (
                self.latest_incremental_state.last_pull_to_timestamp
            )
            self.processing_state.pull_to_timestamp = get_current_datetime()
        elif self.strategy in [FlowLoadingStrategies.FULL]:
            self.processing_state.pull_from_timestamp = None
            self.processing_state.pull_to_timestamp = get_current_datetime()
        elif self.strategy in [FlowLoadingStrategies.BACKFILL]:
            self.processing_state.pull_from_timestamp = (
                self.incremental_parameters.pull_from
            )
            self.processing_state.pull_to_timestamp = (
                self.incremental_parameters.pull_to
            )
        elif self.strategy in [FlowLoadingStrategies.BACKFILL_DELTA]:
            self.processing_state.pull_from_timestamp = (
                self.incremental_parameters.pull_from
            )
            self.processing_state.pull_to_timestamp = get_current_datetime()
        else:
            raise NotImplementedError(
                f"The method 'update_processing_state' is not implemented "
                f"for data load strategy {self.strategy}"
            )

    def is_planned_processing_state_fresh(
        self,
        planned_processing_state: BySourceTstPlannedProcessingState,
    ) -> bool:
        """Whether a by_source_tst plan still matches the latest baseline.

        BACKFILL and FULL windows are explicit and never go stale. A
        BACKFILL_DELTA plan is fresh only when its last status change happened
        after the last run, i.e. after the baseline ``last_pull_to_timestamp``.
        A DELTA plan adds that its ``pull_from_timestamp`` still equals that
        baseline watermark, since DELTA derives its window from it.
        """
        detailled_state = planned_processing_state.detailled_state
        if detailled_state.strategy in [
            FlowLoadingStrategies.BACKFILL,
            FlowLoadingStrategies.FULL,
        ]:
            return True
        # No baseline means this is the first run, so no later run can have
        # superseded the plan and it is fresh by definition.
        if self.latest_incremental_state is None:
            return True
        baseline_timestamp = self.latest_incremental_state.last_pull_to_timestamp
        plan_changed_after_last_run = (
            baseline_timestamp is None
            or planned_processing_state.status_changed_at > baseline_timestamp
        )
        if detailled_state.strategy in [FlowLoadingStrategies.BACKFILL_DELTA]:
            return plan_changed_after_last_run
        if detailled_state.strategy in [FlowLoadingStrategies.DELTA]:
            return plan_changed_after_last_run and (
                detailled_state.pull_from_timestamp == baseline_timestamp
            )
        return True

    @property
    def sql_filter_manager(self) -> IncrementalSqlFilterManager:
        """Return the timestamp-based SQL filter."""
        return BySourceTstSqlFilterManager(
            processing_state=self.processing_state,
        )

    _STATE_UPDATE_STRATEGIES = [
        FlowLoadingStrategies.DELTA,
        FlowLoadingStrategies.FULL,
        FlowLoadingStrategies.BACKFILL_DELTA,
    ]

    def create_post_processing_state(self) -> BySourceTstState:
        self.post_processing_state = BySourceTstState.deep_copy(
            cast(BySourceTstState, self.latest_incremental_state)
        )

        if (
            self.processing_state.succeeded()
            and self.strategy in self._STATE_UPDATE_STRATEGIES
        ):
            self.post_processing_state.last_pull_to_timestamp = (
                self.processing_state.pull_to_timestamp
            )

        return self.post_processing_state
