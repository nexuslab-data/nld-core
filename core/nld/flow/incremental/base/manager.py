from __future__ import annotations

import abc
import datetime
from typing import TYPE_CHECKING, Any, ClassVar, cast

from nld.connector.base.connector import DataConnector
from nld.exceptions import MissingMandatoryArgumentException
from nld.flow.definition.flow_definition import DataFlowStructurePredecessor
from nld.flow.incremental.base.sql_filter_manager import IncrementalSqlFilterManager
from nld.flow.incremental.models import (
    FlowIncrementalLogic,
    FlowIncrementalParams,
    FlowPlannedProcessingState,
    FlowProcessingState,
    FlowSourceState,
    FlowState,
    FlowStatePlan,
    IncrementalPlanStatus,
)
from nld.parameters import (
    ExecutionParameterDefinition,
    apply_default_values_to_parameters,
)
from nld.utils.datetime_util import get_current_datetime
from nld.utils.mixin import NldMixIn

if TYPE_CHECKING:
    from nld.flow.definition.flow_definition import DataFlowDefinition


class IncrementalBackendStateManager[
    DATA_CONNECTOR: DataConnector[Any],
    FLOW_STATE: FlowState,
    FLOW_SOURCE_STATE: FlowSourceState,
    FLOW_PROCESSING_STATE: FlowProcessingState,
    FLOW_PLANNED_PROCESSING_STATE: FlowPlannedProcessingState[Any],
](
    NldMixIn,
    abc.ABC,
):
    """
    Incremental - Backend State Manager

    Manages all read and write methods for incremental state
    """

    # When True, this backend physically implements the planned-state
    # primitives (the state-plan persistence methods plus
    # write/read_planned_processing_state) and can hold a PLANNED plan.
    # Default False so a backend opts in only once it can serve a plan;
    # the execute path never requests a plan a backend cannot store
    # (e.g. a DuckDB state backend), independently of whether the
    # incremental definition supports plans.
    supports_planned_state: ClassVar[bool] = False

    param_definitions: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(
            name="flow_uid",
            mandatory=False,
        ),
    ]

    def __init__(
        self,
        backend_connector: DATA_CONNECTOR,
        flow_namespace: str,
        flow_name: str,
        parameters: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.backend_connector = backend_connector
        self.flow_namespace = flow_namespace
        self.flow_name = flow_name
        self.parameters = apply_default_values_to_parameters(
            parameters, self.get_param_definitions()
        )

    @property
    def flow_uid(self) -> str:
        return self.parameters["flow_uid"]  # type: ignore[no-any-return]

    @classmethod
    def determine_parameters_for_flow_definition(
        cls,
        data_flow_definition: DataFlowDefinition | None,
    ) -> dict[str, Any]:
        """Derive backend parameters from the per-flow typed context.

        Default returns an empty dict. Backend subclasses override to
        translate typed inputs (target structure, predecessors, ...) into
        backend parameter values such as ``s3_root_path``.
        """
        return {}

    @classmethod
    def get_param_definitions(
        cls,
    ) -> list[ExecutionParameterDefinition]:
        return [
            (
                param_definition
                if isinstance(param_definition, ExecutionParameterDefinition)
                else ExecutionParameterDefinition(name=param_definition)
            )
            for param_definition in cls.param_definitions
        ]

    @classmethod
    def get_param_definitions_keys(cls) -> list[str]:
        return [
            param_definition.name for param_definition in cls.get_param_definitions()
        ]

    @classmethod
    def check_param_definitions_dict(cls, params: dict[str, Any]) -> None:
        """
        Check that all mandatory parameter definition parameters are present.

        Args:
            params: Dictionary of parameters to validate

        Raises:
            MissingMandatoryArgumentException: If mandatory parameter is missing
        """
        for param_definition in cls.get_param_definitions():
            if param_definition.name not in params.keys():
                if param_definition.mandatory:
                    raise MissingMandatoryArgumentException(
                        object_type=cls,
                        method_name="check_param_definitions_dict",
                        argument_name=param_definition.name,
                    )

    # Read-only accessor methods (used by `nld flow state` CLI).
    # Default implementations raise NotImplementedError so backends opt-in.
    def read_processing_state(self) -> FLOW_PROCESSING_STATE | None:
        """Return the current persisted processing state for this flow.

        Read-only accessor used by tooling to inspect incremental state
        without starting a flow run. Returns None when no processing state
        has been recorded.
        """
        raise NotImplementedError(
            f"'read_processing_state' is not implemented for {type(self).__name__}"
        )

    def read_post_processing_state(self) -> FLOW_STATE | None:
        """Return the current persisted post-processing state for this flow.

        Read-only accessor used by tooling to inspect incremental state
        without starting a flow run. Returns None when no post-processing
        state has been recorded.
        """
        raise NotImplementedError(
            f"'read_post_processing_state' is not implemented for {type(self).__name__}"
        )

    # Incremental State methods
    def read_current_state(self) -> FLOW_STATE:
        """
        Retrieve the current state

        :return: The key flow state
        """
        raise NotImplementedError("'read_current_state' method is not yet implemented")

    @abc.abstractmethod
    def write_processing_state(
        self,
        processing_flow_state: FLOW_PROCESSING_STATE,
    ) -> None:
        """
        Write the processing flow state to the backend.

        :param processing_flow_state: the processing flow state to write
        """
        raise NotImplementedError(
            "'write_processing_state' method is not yet implemented"
        )

    def write_partial_processing_state(
        self,
        processing_flow_state: FLOW_PROCESSING_STATE,
        identifier: Any,
    ) -> None:
        """Write partial processing state with immediate commit."""
        raise NotImplementedError(
            "'write_partial_processing_state' method is not yet implemented"
        )

    @abc.abstractmethod
    def write_post_processing_state(
        self, post_processing_flow_state: FLOW_STATE
    ) -> None:
        """
        Write the post-processing flow state to the backend

        :param post_processing_flow_state: the post-processing flow state to write
        """
        raise NotImplementedError(
            "'write_post_processing_state' method is not yet implemented"
        )

    def write_partial_post_processing_state(
        self,
        post_processing_flow_state: FLOW_STATE,
        identifier: Any,
    ) -> None:
        """Write partial post-processing state with immediate commit."""
        raise NotImplementedError(
            "'write_partial_post_processing_state' method is not yet implemented"
        )

    # Planned-state reads — backend-level reads from the state store.
    #
    # The backend exposes only the PLANNED listing: a pure read composed
    # from the state-plan persistence primitives below. Assembling the
    # single active plan (state plan + strategy-specific processing state
    # into the typed wrapper) and the planned lifecycle (cancel-on-supersede,
    # COMPLETED / CANCELLED transitions) are both owned by
    # ``IncrementalStateManager``, never by a backend.
    def read_planned_processing_states(
        self,
    ) -> list[FlowStatePlan]:
        """Return every PLANNED state plan for this flow, newest first."""
        planned = [
            state_plan
            for state_plan in self.read_state_plans()
            if state_plan.status == IncrementalPlanStatus.PLANNED
        ]
        return sorted(
            planned,
            key=lambda state_plan: state_plan.computed_at,
            reverse=True,
        )

    # Connector-specific state-plan persistence — opt-in per backend.
    #
    # These carry no lifecycle logic: they only write, read and list the
    # state plans and write/read the strategy-specific processing state.
    # Every planned-state behaviour composes from them — the PLANNED listing
    # just above and the active-plan assembly, writes and transitions on
    # ``IncrementalStateManager``.
    def read_state_plan(
        self,
        plan_state_uid: str,
    ) -> FlowStatePlan | None:
        """Return the state plan for ``plan_state_uid`` scoped to this flow."""
        raise NotImplementedError(
            f"'read_state_plan' is not implemented for {type(self).__name__}",
        )

    def read_state_plans(
        self,
    ) -> list[FlowStatePlan]:
        """Return every state plan for this flow, any status."""
        raise NotImplementedError(
            f"'read_state_plans' is not implemented for {type(self).__name__}",
        )

    def write_state_plan(
        self,
        state_plan: FlowStatePlan,
    ) -> None:
        """Insert or update a single state plan."""
        raise NotImplementedError(
            f"'write_state_plan' is not implemented for {type(self).__name__}",
        )

    def read_planned_processing_state(
        self,
        plan_state_uid: str,
    ) -> FLOW_PROCESSING_STATE | None:
        """Read the strategy-specific processing state for an existing plan."""
        raise NotImplementedError(
            f"'read_planned_processing_state' is not implemented "
            f"for {type(self).__name__}",
        )

    def write_planned_processing_state(
        self,
        plan_state_uid: str,
        processing_state: FLOW_PROCESSING_STATE,
    ) -> None:
        """Persist the strategy-specific processing state for a new PLANNED plan."""
        raise NotImplementedError(
            f"'write_planned_processing_state' is not implemented "
            f"for {type(self).__name__}",
        )


class IncrementalStateManager[
    FLOW_STATE: FlowState,
    FLOW_SOURCE_STATE: FlowSourceState,
    FLOW_PROCESSING_STATE: FlowProcessingState,
    FLOW_PLANNED_PROCESSING_STATE: FlowPlannedProcessingState[Any],
    FLOW_INCREMENTAL_PARAMS: FlowIncrementalParams,
](
    NldMixIn,
    abc.ABC,
):
    """
    Incremental - State Manager

    Manages all the incremental state operations. Can operate with or without
    a backend state manager.
    """

    flow_incremental_logic: ClassVar[FlowIncrementalLogic[Any]]
    param_definitions: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(
            name="flow_uid",
            mandatory=False,
        ),
    ]

    def __init__(
        self,
        incremental_parameters: FLOW_INCREMENTAL_PARAMS,
        incremental_state_backend_manager: (
            IncrementalBackendStateManager[Any, Any, Any, Any, Any] | None
        ) = None,
        secondary_incremental_state_backend_manager: (
            IncrementalBackendStateManager[Any, Any, Any, Any, Any] | None
        ) = None,
        parameters: dict[str, Any] | None = None,
    ):
        super().__init__()
        self.incremental_state_backend_manager = incremental_state_backend_manager
        # Secondary backend mirrors processing-state writes only.
        # Reads and post-processing-state writes stay on primary.
        self.secondary_incremental_state_backend_manager = (
            secondary_incremental_state_backend_manager
        )
        self.incremental_parameters = incremental_parameters
        self.parameters = apply_default_values_to_parameters(
            parameters, self.get_param_definitions()
        )

        # State information
        self.latest_incremental_state: FLOW_STATE | None = None
        self.source_state: FLOW_SOURCE_STATE | None = None
        self.used_planned_processing_state: FLOW_PLANNED_PROCESSING_STATE | None = None
        self.processing_state: FLOW_PROCESSING_STATE | None = None
        self.post_processing_state: FLOW_STATE | None = None

        is_allowed, reason = (
            self.incremental_parameters.is_incremental_parameters_allowed()
        )
        if not is_allowed:
            raise RuntimeError(
                f"The flow cannot be launched due to incremental parameters "
                f"issue: {reason}"
            )

    @classmethod
    def get_param_definitions(cls) -> list[ExecutionParameterDefinition]:
        return [
            (
                param_definition
                if isinstance(param_definition, ExecutionParameterDefinition)
                else ExecutionParameterDefinition(name=param_definition)
            )
            for param_definition in cls.param_definitions
        ]

    @classmethod
    def get_param_definitions_keys(cls) -> list[str]:
        return [
            param_definition.name for param_definition in cls.get_param_definitions()
        ]

    @property
    def flow_uid(self) -> str:
        return self.parameters["flow_uid"]  # type: ignore[no-any-return]

    @property
    def strategy(self) -> str:
        return self.incremental_parameters.strategy

    def get_latest_incremental_state(self) -> None:
        """
        Retrieve the latest incremental state from the backend.

        If no backend manager is configured, state remains None.
        """
        if self.incremental_state_backend_manager is not None:
            self.latest_incremental_state = (
                self.incremental_state_backend_manager.read_current_state()
            )
        else:
            self.latest_incremental_state = (
                self.flow_incremental_logic.definition.state_class()
            )

    def set_source_state(self, source_state: FLOW_SOURCE_STATE) -> None:
        self.source_state = source_state

    def set_processing_state(
        self,
        processing_state: FLOW_PROCESSING_STATE,
    ) -> None:
        """Adopt an externally provided processing state.

        Used when executing from a planned state instead of recomputing it,
        so the rest of the lifecycle consumes the plan's processing state.
        """
        self.processing_state = processing_state

    def use_planned_processing_state(
        self,
        planned_processing_state: FLOW_PLANNED_PROCESSING_STATE,
    ) -> None:
        """Execute from a planned processing state instead of recomputing it.

        Records the used plan so the run's post-processing can transition it
        without the task layer having to track the plan identifier itself, and
        sets the live processing state from the plan's payload.
        """
        self.used_planned_processing_state = planned_processing_state
        self.set_processing_state(
            processing_state=planned_processing_state.processing_state,
        )

    def is_planned_processing_state_fresh(
        self,
        planned_processing_state: FLOW_PLANNED_PROCESSING_STATE,
    ) -> bool:
        """Return whether a planned processing state is still up to date.

        A plan is fresh when recomputing now would yield equivalent work.
        The default is always fresh; strategies whose processing state
        derives from the latest incremental state override this to detect a
        plan superseded by a more recent successful run.
        """
        return True

    @abc.abstractmethod
    def init_processing_state(self) -> None:
        raise NotImplementedError(
            "'init_processing_state' method is not yet implemented"
        )

    @abc.abstractmethod
    def update_processing_state(self) -> None:
        """
        Determine the processing state based on incremental and source state.
        """
        raise NotImplementedError(
            "'update_processing_state' method is not yet implemented"
        )

    @abc.abstractmethod
    def create_post_processing_state(self) -> FLOW_STATE:
        """
        Create the post-processing state
        """
        raise NotImplementedError(
            "'create_post_processing_state' method is not yet implemented"
        )

    def create_partial_post_processing_state(self, identifier: Any) -> None:
        """Create or update the post-processing state for a partial identifier."""
        pass

    def save_processing_state_start(self) -> None:
        """Save the processing state to the backend immediately after determination."""
        if self.incremental_state_backend_manager is not None:
            self.incremental_state_backend_manager.write_processing_state(
                self.processing_state,
            )
        if self.secondary_incremental_state_backend_manager is not None:
            try:
                self.secondary_incremental_state_backend_manager.write_processing_state(
                    self.processing_state,
                )
            except Exception as exc:
                self.log_warn(
                    f"Secondary incremental processing-state start write failed "
                    f"(primary remains authoritative): {exc}",
                )

    def save_processed_state(self) -> None:
        """
        Save the processing state to the backend.

        If no backend manager is configured, this is a no-op.
        Mirrored to the secondary backend when configured.
        """
        if self.incremental_state_backend_manager is not None:
            self.incremental_state_backend_manager.write_processing_state(
                self.processing_state
            )
        if self.secondary_incremental_state_backend_manager is not None:
            try:
                self.secondary_incremental_state_backend_manager.write_processing_state(
                    self.processing_state,
                )
            except Exception as exc:
                self.log_warn(
                    f"Secondary incremental processing-state write failed "
                    f"(primary remains authoritative): {exc}",
                )

    def save_partial_processed_state(self, identifier: Any) -> None:
        """Save the processing state for a partial identifier to the backend.

        Default no-op. Strategies that support partial persistence override
        ``_supports_partial_state`` and rely on the base routing here.
        Mirrored to the secondary backend when configured.
        """
        if not self._supports_partial_state():
            return
        if self.incremental_state_backend_manager is not None:
            self.incremental_state_backend_manager.write_partial_processing_state(
                self.processing_state,
                identifier=identifier,
            )
        if self.secondary_incremental_state_backend_manager is not None:
            try:
                self.secondary_incremental_state_backend_manager.write_partial_processing_state(
                    self.processing_state,
                    identifier=identifier,
                )
            except Exception as exc:
                self.log_warn(
                    f"Secondary incremental partial processing-state write failed "
                    f"(primary remains authoritative): {exc}",
                )

    def save_post_processing_state(self) -> None:
        """
        Save the post-processing state to the backend.

        Primary backend only - the post-processing state represents the
        authoritative incremental state and is intentionally NOT mirrored
        to the secondary backend.
        """
        if self.incremental_state_backend_manager is not None:
            self.incremental_state_backend_manager.write_post_processing_state(
                self.post_processing_state
            )

    def save_partial_post_processing_state(self, identifier: Any) -> None:
        """Save the post-processing state for a partial identifier.

        Primary backend only - never mirrored to the secondary backend.
        """
        if not self._supports_partial_state():
            return
        if self.incremental_state_backend_manager is not None:
            self.incremental_state_backend_manager.write_partial_post_processing_state(
                self.post_processing_state,
                identifier=identifier,
            )

    def _supports_partial_state(self) -> bool:
        """Whether this strategy persists partial state per identifier.

        Subclasses opt in by returning True. Default is False so that
        strategies without partial semantics keep the historical no-op.
        """
        return False

    # Planned-state methods — primary backend only.
    #
    # The planned processing state is the single source of truth for a
    # precomputed plan, so it is written and read on the primary backend
    # exclusively. The secondary backend (informational mirror of the
    # live processing state) is intentionally never involved here.
    def save_planned_processing_state(
        self,
        processing_flow_state: FLOW_PROCESSING_STATE,
        plan_state_uid: str,
        computed_at: datetime.datetime,
        requestor: str | None = None,
    ) -> None:
        """Persist a new PLANNED plan on the primary backend.

        The strategy-specific processing state lands first so a reader
        observing the new PLANNED state plan never sees an empty processing
        state; every other PLANNED
        state plan for this flow is then cancelled before the new plan is
        written. The cancel-on-supersede ordering lives here, never on the
        backend, which only persists the records it is handed.
        """
        assert self.incremental_state_backend_manager is not None
        backend = self.incremental_state_backend_manager
        planned_state_class = (
            self.flow_incremental_logic.definition.planned_processing_state_class
        )
        planned_state = planned_state_class(
            plan_state_uid=plan_state_uid,
            flow_namespace=backend.flow_namespace,
            flow_name=backend.flow_name,
            status=IncrementalPlanStatus.PLANNED,
            strategy=self.strategy,
            computed_at=computed_at,
            status_changed_at=computed_at,
            requestor=requestor,
            executed_by_flow_uid=None,
            processing_state=processing_flow_state,
        )
        backend.write_planned_processing_state(
            plan_state_uid=planned_state.plan_state_uid,
            processing_state=planned_state.processing_state,
        )
        cancelled_at = get_current_datetime()
        for state_plan in backend.read_state_plans():
            if state_plan.plan_state_uid == planned_state.plan_state_uid:
                continue
            if state_plan.status != IncrementalPlanStatus.PLANNED:
                continue
            state_plan.status = IncrementalPlanStatus.CANCELLED
            state_plan.status_changed_at = cancelled_at
            backend.write_state_plan(state_plan=state_plan)
        backend.write_state_plan(state_plan=planned_state.to_state_plan())

    @property
    def backend_supports_planned_state(self) -> bool:
        """Whether the primary backend can physically hold a PLANNED plan.

        A flow's incremental definition may support plans while its
        configured state backend cannot store them (e.g. DuckDB). This
        reports the backend-side capability so callers can gate plan
        requests on both layers; False when there is no backend at all.
        """
        backend = self.incremental_state_backend_manager
        return backend is not None and backend.supports_planned_state

    def get_planned_processing_state(
        self,
        plan_state_uid: str | None = None,
    ) -> FLOW_PLANNED_PROCESSING_STATE | None:
        """Return the active PLANNED plan from the primary backend, or None.

        With ``plan_state_uid`` the named plan is returned iff it is still
        PLANNED; without it the most recently ``computed_at`` PLANNED plan
        is returned. A state plan without a recoverable processing state
        yields None.

        The state plan and its strategy-specific processing state are read
        off the backend persistence primitives and assembled here into the typed
        wrapper from ``definition.planned_processing_state_class`` — the
        same source the write path uses — so the backend never needs to
        know the strategy-specific class.
        """
        backend = self.incremental_state_backend_manager
        if backend is None:
            return None
        if plan_state_uid is not None:
            state_plan = backend.read_state_plan(plan_state_uid=plan_state_uid)
            if state_plan is None or state_plan.status != IncrementalPlanStatus.PLANNED:
                return None
        else:
            planned = backend.read_planned_processing_states()
            state_plan = planned[0] if planned else None
        if state_plan is None:
            return None
        processing_state = backend.read_planned_processing_state(
            plan_state_uid=state_plan.plan_state_uid,
        )
        if processing_state is None:
            return None
        planned_state_class = (
            self.flow_incremental_logic.definition.planned_processing_state_class
        )
        return cast(
            FLOW_PLANNED_PROCESSING_STATE,
            planned_state_class(
                plan_state_uid=state_plan.plan_state_uid,
                flow_namespace=state_plan.flow_namespace,
                flow_name=state_plan.flow_name,
                status=state_plan.status,
                strategy=state_plan.strategy,
                computed_at=state_plan.computed_at,
                status_changed_at=state_plan.status_changed_at,
                requestor=state_plan.requestor,
                executed_by_flow_uid=state_plan.executed_by_flow_uid,
                processing_state=processing_state,
            ),
        )

    def get_planned_processing_states(
        self,
    ) -> list[FlowStatePlan]:
        """Return every PLANNED state plan from the primary backend."""
        if self.incremental_state_backend_manager is None:
            return []
        return self.incremental_state_backend_manager.read_planned_processing_states()

    def mark_plan_completed(
        self,
        plan_state_uid: str,
        executed_by_flow_uid: str,
    ) -> None:
        """Transition a consumed PLANNED plan to COMPLETED on the primary backend.

        No-op when no state plan matches ``plan_state_uid``. The transition
        is driven here off the backend persistence primitives so the backend
        stays free of any lifecycle rule.
        """
        assert self.incremental_state_backend_manager is not None
        backend = self.incremental_state_backend_manager
        state_plan = backend.read_state_plan(plan_state_uid=plan_state_uid)
        if state_plan is None:
            return
        state_plan.status = IncrementalPlanStatus.COMPLETED
        state_plan.status_changed_at = get_current_datetime()
        state_plan.executed_by_flow_uid = executed_by_flow_uid
        backend.write_state_plan(state_plan=state_plan)

    def mark_plan_cancelled(
        self,
        plan_state_uid: str,
    ) -> None:
        """Transition a PLANNED plan to CANCELLED on the primary backend.

        No-op unless a still-PLANNED state plan matches ``plan_state_uid``.
        The transition is driven here off the backend persistence primitives
        so the backend stays free of any lifecycle rule.
        """
        assert self.incremental_state_backend_manager is not None
        backend = self.incremental_state_backend_manager
        state_plan = backend.read_state_plan(plan_state_uid=plan_state_uid)
        if state_plan is None:
            return
        if state_plan.status != IncrementalPlanStatus.PLANNED:
            return
        state_plan.status = IncrementalPlanStatus.CANCELLED
        state_plan.status_changed_at = get_current_datetime()
        backend.write_state_plan(state_plan=state_plan)

    @property
    @abc.abstractmethod
    def sql_filter_manager(self) -> IncrementalSqlFilterManager:
        """Return the SQL filter for this incremental strategy."""
        raise NotImplementedError("'sql_filter' property is not yet implemented")

    def apply_sql_filter(
        self,
        sql_query: str,
        predecessors: dict[str, DataFlowStructurePredecessor],
        dialect: str,
    ) -> str:
        """Apply incremental WHERE clause filtering to the SQL query."""
        return self.sql_filter_manager.apply_filter(
            sql_query=sql_query,
            predecessors=predecessors,
            dialect=dialect,
        )

    def get_deleted_state(self) -> None:
        # TODO : Fill this method
        # Is this needed ?
        pass
