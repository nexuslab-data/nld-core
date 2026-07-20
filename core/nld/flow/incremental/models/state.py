import abc
import datetime
from typing import Any

from nld.pydantic import NldBaseModel


class FlowState(NldBaseModel):
    @abc.abstractmethod
    def render_state_text(self) -> str:
        """Return the operator-facing text rendering of this state.

        Each strategy owns its own layout so the generic ``nld flow state``
        renderer stays free of strategy-specific field knowledge.
        """
        raise NotImplementedError(
            "The method 'render_state_text' should be implemented in sub class."
        )


class FlowProcessingState(NldBaseModel):
    flow_uid: str
    strategy: str

    @abc.abstractmethod
    def get_display_log(self) -> str:
        """Return a human-readable summary of the processing state."""
        raise NotImplementedError(
            "The method 'get_display_log' should be implemented in sub class."
        )

    @abc.abstractmethod
    def render_state_text(self) -> str:
        """Return the operator-facing text rendering of this processing state.

        Each strategy owns its own layout so the generic ``nld flow state``
        renderer stays free of strategy-specific field knowledge.
        """
        raise NotImplementedError(
            "The method 'render_state_text' should be implemented in sub class."
        )

    def get_pull_timestamps(
        self,
    ) -> tuple[datetime.datetime | None, datetime.datetime | None]:
        """Return (pull_from, pull_to) timestamps if applicable.

        Subclasses with timestamp-based incremental strategies
        should override this to return their actual timestamps.
        """
        return None, None


class FlowSourceState(NldBaseModel):
    pass


class PlannedStateStrategy:
    """How ``nld flow execute`` reacts to an available planned state.

    AUTO (the default) adopts a planned state only when it is still consistent
    with the latest incremental state, recomputing otherwise. TRUST adopts it
    as-is. RECOMPUTE ignores any plan. STRICT fails when no plan exists or the
    plan is stale.
    """

    AUTO = "auto"
    TRUST = "trust"
    RECOMPUTE = "recompute"
    STRICT = "strict"


PLANNED_STATE_STRATEGIES = [
    PlannedStateStrategy.AUTO,
    PlannedStateStrategy.RECOMPUTE,
    PlannedStateStrategy.STRICT,
    PlannedStateStrategy.TRUST,
]


class FlowStatePlan(NldBaseModel):
    """Lifecycle metadata of a precomputed processing-state plan.

    Carries every plan field except the strategy-specific
    processing-state payload. The generic plan lifecycle
    (cancel-on-supersede and COMPLETED / CANCELLED transitions) is driven
    off this record by ``IncrementalStateManager``, and the latest-PLANNED
    selection by ``IncrementalBackendStateManager``, so no connector
    backend has to re-implement either.
    """

    plan_state_uid: str
    flow_namespace: str
    flow_name: str
    status: str
    strategy: str
    computed_at: datetime.datetime
    status_changed_at: datetime.datetime
    requestor: str | None = None
    executed_by_flow_uid: str | None = None


class FlowPlannedProcessingDetailledState[ProcessingState: FlowProcessingState](
    NldBaseModel,
):
    """Strategy-specific detail a PLANNED plan carries.

    Mirrors the live processing state but is plan-time only: it may omit or
    rename execution-outcome fields. Keyed on ``plan_state_uid`` so it maps onto
    the persisted planned-state row. Generic over ``ProcessingState`` so the
    converters below are typed per strategy.
    """

    plan_state_uid: str

    @abc.abstractmethod
    def to_processing_state(self, flow_uid: str) -> ProcessingState:
        """Build the live processing state a run executes from.

        Execution-outcome fields are defaulted because a plan has not run.
        """
        raise NotImplementedError(
            "The method 'to_processing_state' should be implemented in sub class."
        )

    @classmethod
    @abc.abstractmethod
    def from_processing_state(
        cls,
        plan_state_uid: str,
        processing_state: ProcessingState,
    ) -> "FlowPlannedProcessingDetailledState[ProcessingState]":
        """Build the plan-time detail from a freshly computed processing state."""
        raise NotImplementedError(
            "The method 'from_processing_state' should be implemented in sub class."
        )


class FlowPlannedProcessingState[
    DetailledState: FlowPlannedProcessingDetailledState[Any]
](
    FlowStatePlan,
):
    """A state plan plus its strategy-specific planned detail payload.

    The strategy-specific payload is carried under ``detailled_state`` so a
    single plan schema covers every strategy. The payload is a
    ``FlowPlannedProcessingDetailledState`` (plan-time only), decoupled from the
    live processing state.
    """

    detailled_state: DetailledState

    def to_state_plan(self) -> FlowStatePlan:
        """Return the lifecycle metadata without the planned-detail payload."""
        return FlowStatePlan(
            plan_state_uid=self.plan_state_uid,
            flow_namespace=self.flow_namespace,
            flow_name=self.flow_name,
            status=self.status,
            strategy=self.strategy,
            computed_at=self.computed_at,
            status_changed_at=self.status_changed_at,
            requestor=self.requestor,
            executed_by_flow_uid=self.executed_by_flow_uid,
        )
