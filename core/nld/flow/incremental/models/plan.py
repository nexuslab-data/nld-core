import datetime

from nld.flow.incremental.models.state import FlowProcessingState
from nld.pydantic import NldBaseModel


class IncrementalPlanStatus:
    PLANNED = "PLANNED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


INCREMENTAL_PLAN_STATUS = [
    IncrementalPlanStatus.CANCELLED,
    IncrementalPlanStatus.COMPLETED,
    IncrementalPlanStatus.PLANNED,
]


class PlannedStateStrategy:
    """How ``nld flow execute`` reacts to an available planned state.

    AUTO adopts a planned state only when it is still consistent with the
    latest incremental state, recomputing otherwise. TRUST adopts it as-is.
    RECOMPUTE ignores any plan (the default, today's behavior). STRICT fails
    when no plan exists or the plan is stale.
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


class FlowPlannedProcessingState[ProcessingState: FlowProcessingState](
    FlowStatePlan,
):
    """A state plan plus its strategy-specific processing-state payload.

    The strategy-specific payload is carried verbatim under
    ``processing_state`` so a single plan schema covers every strategy.
    """

    processing_state: ProcessingState

    def to_state_plan(self) -> FlowStatePlan:
        """Return the lifecycle metadata without the processing-state payload."""
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
