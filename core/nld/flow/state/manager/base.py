import datetime
from typing import Any

from nld.flow.execution import (
    ExecutionStateManager,
    FlowExecutionHistory,
    FlowExecutionInfo,
    FlowExecutionState,
    FlowStepExecutionInfo,
)
from nld.flow.incremental.base import (
    IncrementalStateManager,
)
from nld.flow.incremental.models import (
    FlowIncrementalLogic,
    FlowPlannedProcessingState,
    FlowProcessingState,
    FlowSourceState,
    FlowState,
    FlowStatePlan,
)


class FlowStateManager[
    FLOW_STATE: FlowState,
    FLOW_SOURCE_STATE: FlowSourceState,
    FLOW_PROCESSING_STATE: FlowProcessingState,
    FLOW_PLANNED_PROCESSING_STATE: FlowPlannedProcessingState[Any],
]:
    """
    State Manager

    Manages all the execution and incremental state operations
    """

    def __init__(
        self,
        execution_state_manager: ExecutionStateManager,
        incremental_state_manager: IncrementalStateManager[Any, Any, Any, Any, Any],
    ):
        self.execution_state_manager = execution_state_manager
        self.incremental_state_manager = incremental_state_manager

    # Execution methods
    @property
    def data_load_strategy(self) -> str:
        return self.execution_state_manager.data_load_strategy

    @property
    def current_execution_info(self) -> "FlowExecutionInfo":
        return self.execution_state_manager.current_execution_info

    @property
    def execution_state(self) -> FlowExecutionState | None:
        return self.execution_state_manager.previous_execution_state

    @property
    def execution_history(self) -> FlowExecutionHistory | None:
        return self.execution_state_manager.execution_history

    def get_latest_execution_state(self) -> None:
        self.execution_state_manager.get_latest_execution_state()

    def _should_auto_transition_processing_state(self) -> bool:
        """Check if processing state auto-transition is enabled."""
        if self.processing_state is None:
            return False
        definition = self.incremental_state_manager.flow_incremental_logic.definition
        return definition.auto_processing_state_transition

    def was_partial_state_persistence_used(self) -> bool:
        """Check if partial state persistence was used during this run."""
        definition = self.incremental_state_manager.flow_incremental_logic.definition
        if not definition.partial_state_persistence:
            return False
        return self.incremental_state_manager.post_processing_state is not None

    def update_execution_status_to_completed(self, with_warning: bool = False) -> None:
        self.execution_state_manager.update_execution_status_to_completed(
            with_warning=with_warning,
        )
        if self._should_auto_transition_processing_state():
            self.processing_state.set_to_succeeded()  # type: ignore[union-attr]

    def update_execution_status_to_failed(
        self,
        error_message: str | None = None,
    ) -> None:
        self.execution_state_manager.update_execution_status_to_failed(
            error_message=error_message,
        )
        if self._should_auto_transition_processing_state():
            self.processing_state.set_to_failed(  # type: ignore[union-attr]
                error_message=error_message,
            )

    def update_global_execution_state(self) -> None:
        self.execution_state_manager.update_global_execution_state()

    def save_execution_start(self) -> None:
        """Save execution info header to backend at flow start."""
        self.execution_state_manager.save_execution_start()

    def save_step_completed(
        self,
        step_info: FlowStepExecutionInfo,
    ) -> None:
        """Save a single step to backend after completion."""
        self.execution_state_manager.save_step_completed(
            step_info=step_info,
        )

    def save_all_execution_infos(self, without_state: bool = False) -> None:
        self.execution_state_manager.save_all_execution_infos(
            without_state=without_state,
        )

    # Incremental methods
    @property
    def flow_definition(self) -> "FlowIncrementalLogic[Any]":
        return self.incremental_state_manager.flow_incremental_logic

    @property
    def incremental_parameters(self) -> Any:
        return self.incremental_state_manager.incremental_parameters

    @property
    def latest_incremental_state(self) -> FLOW_STATE | None:
        return self.incremental_state_manager.latest_incremental_state

    @property
    def source_state(self) -> FLOW_SOURCE_STATE | None:
        return self.incremental_state_manager.source_state

    @property
    def processing_state(self) -> FLOW_PROCESSING_STATE | None:
        return self.incremental_state_manager.processing_state

    @property
    def post_processing_state(self) -> FLOW_STATE | None:
        return self.incremental_state_manager.post_processing_state

    @property
    def used_planned_processing_state(
        self,
    ) -> FLOW_PLANNED_PROCESSING_STATE | None:
        """Return the planned processing state used for this run, if any."""
        return self.incremental_state_manager.used_planned_processing_state

    @property
    def backend_supports_planned_state(self) -> bool:
        """Whether the primary state backend can hold a PLANNED plan."""
        return self.incremental_state_manager.backend_supports_planned_state

    def get_latest_incremental_state(self) -> None:
        self.incremental_state_manager.get_latest_incremental_state()

    def set_source_state(self, source_state: FLOW_SOURCE_STATE) -> None:
        self.incremental_state_manager.set_source_state(source_state)

    def init_processing_state(self) -> None:
        self.incremental_state_manager.init_processing_state()

    def update_processing_state(self) -> None:
        self.incremental_state_manager.update_processing_state()
        self._propagate_pull_timestamps_to_execution_info()

    def _propagate_pull_timestamps_to_execution_info(self) -> None:
        """Copy pull timestamps from processing state to execution info."""
        if self.processing_state is None:
            return
        pull_from, pull_to = self.processing_state.get_pull_timestamps()
        self.current_execution_info.pull_from = pull_from
        self.current_execution_info.pull_to = pull_to

    def create_post_processing_state(self) -> FLOW_STATE:
        return self.incremental_state_manager.create_post_processing_state()  # type: ignore[no-any-return]

    def save_processing_state_start(self) -> None:
        """Save the initial processing state to the backend with immediate commit."""
        self.incremental_state_manager.save_processing_state_start()

    def save_processed_state(self) -> None:
        self.incremental_state_manager.save_processed_state()

    def save_post_processing_state(self) -> None:
        self.incremental_state_manager.save_post_processing_state()

    def create_partial_post_processing_state(self, identifier: Any) -> None:
        """Create or update the post-processing state for a partial identifier."""
        self.incremental_state_manager.create_partial_post_processing_state(
            identifier,
        )

    def save_partial_processed_state(self, identifier: Any) -> None:
        """Save the processing state for a partial identifier to the backend."""
        self.incremental_state_manager.save_partial_processed_state(identifier)

    def save_partial_post_processing_state(self, identifier: Any) -> None:
        """Save the post-processing state for a partial identifier to the backend."""
        self.incremental_state_manager.save_partial_post_processing_state(
            identifier,
        )

    # Planned State methods
    def save_planned_processing_state(
        self,
        processing_flow_state: FLOW_PROCESSING_STATE,
        plan_state_uid: str,
        computed_at: datetime.datetime,
        requestor: str | None = None,
    ) -> None:
        """Persist a precomputed processing state as a PLANNED plan."""
        self.incremental_state_manager.save_planned_processing_state(
            processing_flow_state=processing_flow_state,
            plan_state_uid=plan_state_uid,
            computed_at=computed_at,
            requestor=requestor,
        )

    def get_planned_processing_state(
        self,
        plan_state_uid: str | None = None,
    ) -> FLOW_PLANNED_PROCESSING_STATE | None:
        """Return the active PLANNED plan from the primary backend."""
        return self.incremental_state_manager.get_planned_processing_state(
            plan_state_uid=plan_state_uid,
        )

    def get_planned_processing_states(
        self,
    ) -> list[FlowStatePlan]:
        """Return every PLANNED state plan from the primary backend."""
        return self.incremental_state_manager.get_planned_processing_states()

    def is_planned_processing_state_fresh(
        self,
        planned_processing_state: FLOW_PLANNED_PROCESSING_STATE,
    ) -> bool:
        """Return whether a planned processing state is still up to date."""
        return self.incremental_state_manager.is_planned_processing_state_fresh(
            planned_processing_state=planned_processing_state,
        )

    def use_planned_processing_state(
        self,
        planned_processing_state: FLOW_PLANNED_PROCESSING_STATE,
    ) -> None:
        """Execute from a planned processing state instead of recomputing.

        Records the used plan on the incremental state manager, sets the
        live processing state and propagates its pull timestamps to the current
        execution info, mirroring ``update_processing_state``.
        """
        self.incremental_state_manager.use_planned_processing_state(
            planned_processing_state=planned_processing_state,
        )
        self._propagate_pull_timestamps_to_execution_info()

    def update_plan_state_to_completed(
        self,
        plan_state_uid: str,
        executed_by_flow_uid: str,
    ) -> None:
        """Transition a consumed PLANNED plan to COMPLETED."""
        self.incremental_state_manager.mark_plan_completed(
            plan_state_uid=plan_state_uid,
            executed_by_flow_uid=executed_by_flow_uid,
        )

    def update_plan_state_to_cancelled(
        self,
        plan_state_uid: str,
    ) -> None:
        """Transition a PLANNED plan to CANCELLED."""
        self.incremental_state_manager.mark_plan_cancelled(
            plan_state_uid=plan_state_uid,
        )

    # Deleted State methods
    def get_deleted_state(self) -> None:
        self.incremental_state_manager.get_deleted_state()
