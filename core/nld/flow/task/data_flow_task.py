import abc
import datetime
from typing import Any, ClassVar

from nld.connector.base import (
    QueryExecResultFormatter,
)
from nld.connector.base.query import QueryExecResult
from nld.flow.definition import (
    DataFlowDefinition,
    NamespacedDataFlowDefinition,
)
from nld.flow.exceptions import (
    NoPlannedStateException,
    StalePlannedStateException,
)
from nld.flow.execution import FlowExecutionInfo
from nld.flow.execution.decorator import track_flow_step
from nld.flow.incremental.impl.no_increment.logic import (
    NO_INCREMENT_FLOW_INCREMENTAL_LOGIC,
)
from nld.flow.incremental.models import (
    FlowIncrementalLogic,
    IncrementalConfig,
    PlannedStateStrategy,
)
from nld.flow.state.factory import FlowStateManagerFactory
from nld.flow.state.manager import FlowStateManager
from nld.flow.state.state_backend_connector_resolver import (
    StateBackendConnectorWrapper,
)
from nld.flow.utils import (
    FlowExecStatus,
    FlowLoadingStrategies,
    FlowStepCategory,
)
from nld.parameters.execution_params_def import (
    ExecutionParameterDefinition,
)
from nld.task import BaseTask
from nld.utils.datetime_util import get_current_datetime
from nld.utils.string_utils import split_camel_case_string

DATA_CONNECTOR_INIT_PARAM_SUFFIX = "_connector"


class DataFlowTask(BaseTask, abc.ABC):
    """
    Data Flow Task.

    Subclasses may set ``_INCREMENTAL_LOGIC`` to declare a default
    incremental logic at the class level. It is no longer mandatory:
    flows can override it through their ``incremental`` config in
    YAML, in which case the per-flow logic is resolved by
    ``DataFlowDefinition.resolve_incremental_logic`` and used in place
    of the ClassVar.
    """

    _INCREMENTAL_LOGIC: ClassVar[FlowIncrementalLogic[Any] | None] = None

    init_params = [
        ExecutionParameterDefinition(
            name="namespaced_data_flow_definition",
            mandatory=False,
        ),
    ]
    run_params = []

    def __init__(
        self,
        flow_execution_info: FlowExecutionInfo | None = None,
        namespaced_data_flow_definition: NamespacedDataFlowDefinition | None = None,
        state_backend_connector_wrapper: StateBackendConnectorWrapper | None = None,
        task_uuid: str | None = None,
        task_name: str | None = None,
        namespace: str | None = None,
        instance_name: str | None = None,
        started_at: datetime.datetime | None = None,
        planned_state_strategy: str = PlannedStateStrategy.AUTO,
        **kwargs: Any,
    ):
        if namespaced_data_flow_definition is not None and namespace is not None:
            raise ValueError(
                "'namespace' must be None when 'namespaced_data_flow_definition' "
                "is provided: the namespace is derived from the data flow definition.",
            )

        if flow_execution_info is not None and any(
            override is not None
            for override in (
                task_uuid,
                task_name,
                namespace,
                instance_name,
                started_at,
            )
        ):
            raise ValueError(
                "'task_uuid', 'task_name', 'namespace', 'instance_name' and "
                "'started_at' must be None when 'flow_execution_info' is provided: "
                "their values are derived from the flow execution info.",
            )

        # Initialization of Base Task with execution UUID and logger
        super().__init__(
            exec_uuid=(
                flow_execution_info.flow_uid
                if flow_execution_info is not None
                else task_uuid
            ),
        )

        self.log_prefix: str = ""

        self._state_backend_connector_wrapper = state_backend_connector_wrapper
        self._state_manager: FlowStateManager[Any, Any, Any, Any] | None = None
        self.namespaced_data_flow_definition = namespaced_data_flow_definition
        self.planned_state_strategy = planned_state_strategy

        self._incremental_init_params = (
            self.incremental_logic.definition.create_incremental_parameters(**kwargs)
        )

        if namespaced_data_flow_definition is not None:
            namespace = str(namespaced_data_flow_definition.namespace)
            if task_name is None:
                task_name = namespaced_data_flow_definition.model.name

        self.name = self.init_name(task_name)

        self.flow_execution_info = self._init_flow_execution_info(
            flow_execution_info=flow_execution_info,
            namespace=namespace,
            instance_name=instance_name,
            started_at=started_at,
        )

    def _init_flow_execution_info(
        self,
        flow_execution_info: FlowExecutionInfo | None,
        namespace: str | None,
        instance_name: str | None,
        started_at: datetime.datetime | None,
    ) -> FlowExecutionInfo:
        """Return the provided flow execution info or build one from overrides."""
        if flow_execution_info is not None:
            return flow_execution_info
        return FlowExecutionInfo(
            flow_uid=self.exec_uuid,
            flow_namespace=namespace if namespace is not None else "#",
            flow_name=self.name,
            flow_instance_name=instance_name if instance_name is not None else "#",
            requestor="#",
            data_load_strategy=self.incremental_logic.definition.default_strategy,
            started_at=(
                started_at if started_at is not None else get_current_datetime()
            ),
            steps=[],
        )

    @property
    def context(self) -> Any:
        """Get the current NLD execution context."""
        from nld.task.context import NldExecutionContext

        return NldExecutionContext.require_current()

    @property
    def entity_registry(self) -> Any:
        """Get the entity registry from the current execution context."""
        return self.context.entity_registry

    @property
    def state_manager(self) -> FlowStateManager[Any, Any, Any, Any]:
        """Get the state manager, raising if not yet initialized."""
        if self._state_manager is None:
            raise RuntimeError(
                "state_manager is not initialized. "
                "Call init_state_manager() before accessing state_manager."
            )
        return self._state_manager

    @state_manager.setter
    def state_manager(
        self,
        value: FlowStateManager[Any, Any, Any, Any] | None,
    ) -> None:
        self._state_manager = value

    @property
    def incremental_parameters(self) -> Any:
        """
        Get incremental parameters from the state manager.

        Returns:
            The incremental parameters from the incremental state manager
        """
        return self.state_manager.incremental_state_manager.incremental_parameters

    @property
    def data_flow_definition(self) -> DataFlowDefinition | None:
        """Return the unwrapped DataFlowDefinition, or None."""
        if self.namespaced_data_flow_definition is None:
            return None
        return self.namespaced_data_flow_definition.model

    @property
    def incremental_config(self) -> IncrementalConfig | None:
        """Return the incremental config, or None."""
        if self.data_flow_definition is None:
            return None
        return self.data_flow_definition.incremental

    @property
    def incremental_logic(self) -> FlowIncrementalLogic[Any]:
        """Return the incremental logic for this task instance.

        Resolution priority:
          1. Per-flow logic from ``data_flow_definition.resolve_incremental_logic``.
          2. The task class ``_INCREMENTAL_LOGIC`` ClassVar.
          3. ``NO_INCREMENT_FLOW_INCREMENTAL_LOGIC`` fallback.
        """
        if self.data_flow_definition is not None:
            return self.data_flow_definition.resolve_incremental_logic(
                task_class=type(self),
            )
        class_logic = type(self)._INCREMENTAL_LOGIC
        if class_logic is not None:
            return class_logic
        return NO_INCREMENT_FLOW_INCREMENTAL_LOGIC

    @property
    def incremental_definition(self) -> Any:
        """Return the incremental definition from the resolved logic."""
        return self.incremental_logic.definition

    def init_name(self, task_name: str | None) -> str:
        return (
            task_name
            if task_name is not None
            else "_".join(split_camel_case_string(self.__class__.__name__)).lower()
        )

    def init_state_manager(self) -> FlowStateManager[Any, Any, Any, Any]:
        flow_state_manager_factory = FlowStateManagerFactory()
        flow_state_manager = flow_state_manager_factory.create_flow_state_manager(
            state_backend_connector_wrapper=self._state_backend_connector_wrapper,
            flow_execution_info=self.flow_execution_info,
            incremental_type=self.incremental_logic.definition.category.lower(),
            data_flow_definition=self.data_flow_definition,
            **self._incremental_init_params,
        )
        self.state_manager = flow_state_manager

        # Update strategy from the resolved incremental parameters
        if hasattr(self.state_manager, "incremental_state_manager"):
            resolved_strategy = self.incremental_parameters.strategy
            self.flow_execution_info.data_load_strategy = resolved_strategy

        return flow_state_manager

    @classmethod
    def get_class_incremental_logic(cls) -> FlowIncrementalLogic[Any] | None:
        """Return the class-level incremental logic ClassVar, or None.

        Introspection accessor only — for runtime resolution that honors
        the per-flow YAML ``incremental`` config, use the
        ``incremental_logic`` instance property or
        ``DataFlowDefinition.resolve_incremental_logic``.
        """
        return cls._INCREMENTAL_LOGIC

    # Parameters methods
    @classmethod
    def get_connector_init_params(cls) -> list[str]:
        """
        Get the list of data connector parameters.

        All data connector parameters need to be provided as an init parameter.
        """
        return [
            param_definition.name
            for param_definition in cls.get_init_params()
            if param_definition.name.endswith(DATA_CONNECTOR_INIT_PARAM_SUFFIX)
        ]

    _QUERY_RESULT_FORMATTER: ClassVar[QueryExecResultFormatter] = (
        QueryExecResultFormatter()
    )

    def log_info(self, message: str) -> None:
        super().log_info(self._prefix_message(message=message))

    def log_warn(self, message: str) -> None:
        super().log_warn(self._prefix_message(message=message))

    def log_error(self, message: str) -> None:
        super().log_error(self._prefix_message(message=message))

    def _prefix_message(self, message: str) -> str:
        """Prepend the optional batch prefix (e.g. `[1/3]`) to a log line."""
        if not self.log_prefix:
            return message
        return f"{self.log_prefix} {message}"

    def _append_steps_from_results(
        self,
        query_results: list[QueryExecResult],
        strategy_name: str,
        step_category: str | None = None,
    ) -> None:
        """Convert query results to steps and append to execution info."""
        from nld.flow.sql.sql_step_converter import convert_query_result_to_step

        for query_result in query_results:
            step = convert_query_result_to_step(
                query_result,
                flow_uid=self.flow_execution_info.flow_uid,
                strategy_name=strategy_name,
                step_category=step_category,
            )
            if self.flow_execution_info.steps is None:
                self.flow_execution_info.steps = []
            self.flow_execution_info.steps.append(step)

            self._log_query_result(
                query_result=query_result,
                strategy_name=strategy_name,
            )

            if (
                self._state_manager is not None
                and self._is_immediate_step_persistence_enabled()
            ):
                self.state_manager.save_step_completed(step_info=step)

    def _log_query_result(
        self,
        query_result: QueryExecResult,
        strategy_name: str,
    ) -> None:
        """Emit a single-line row-count summary for each executed query.

        Output looks like `[i/N] 439,843 rows merged` once the batch
        prefix is applied by `log_info`. Failures surface the error via
        `log_warn`. Subclasses can override this method or swap
        `_QUERY_RESULT_FORMATTER` on the class for richer output.
        """
        rendered = self._QUERY_RESULT_FORMATTER.format_row_count_line(
            result=query_result,
        )
        if query_result.failed():
            self.log_warn(rendered)
        else:
            self.log_info(rendered)

    # Run standard methods
    @abc.abstractmethod
    def run_flow(self) -> None:
        """
        Execute the main flow logic.

        This method must be implemented by subclasses to define the specific flow logic.
        """
        raise NotImplementedError(
            "The method 'run_flow' should be implemented in sub class."
        )

    # Pre-processing methods
    def pre_processing(self) -> None:
        """
        Execute all pre-processing methods in sequence.

        Orchestrates pre-processing at start, for execution, and state mgmt.
        """
        self.pre_processing_at_start()
        self.get_latest_execution_state()
        self.get_incremental_state()

    def get_incremental_state(self) -> None:
        """Use an available planned state or compute one, per the strategy.

        Honors ``planned_state_strategy`` (see ``PlannedStateStrategy``):
        RECOMPUTE always computes; AUTO/STRICT/TRUST consult the active
        PLANNED plan and, except for TRUST, validate it against the latest
        incremental state before using it.
        """
        definition = self.incremental_definition
        if not definition.tracks_state:
            return

        # Plans are gated on two independent layers: the incremental
        # definition must support plans, and the configured state backend
        # must be able to hold one (e.g. DuckDB cannot). When either is off,
        # plans cannot exist for this flow, so disregard the planned-state
        # strategy entirely and just recompute the incremental state.
        if (
            not definition.supports_planned_state
            or not self.state_manager.backend_supports_planned_state
        ):
            self.compute_incremental_state()
            return

        # Plans are possible here, so honor the planned-state strategy.
        if self.planned_state_strategy == PlannedStateStrategy.RECOMPUTE:
            self.compute_incremental_state()
            return

        available_planned_processing_state = (
            self.state_manager.get_planned_processing_state()
        )

        if available_planned_processing_state is None:
            if self.planned_state_strategy == PlannedStateStrategy.STRICT:
                raise NoPlannedStateException(
                    flow_namespace=self.flow_execution_info.flow_namespace,
                    flow_name=self.flow_execution_info.flow_name,
                )
            self.compute_incremental_state()
            return

        # The baseline is needed both for the freshness check and, later, for
        # building the post-processing state, so retrieve it once here.
        self.retrieve_latest_incremental_state()
        self._save_last_step_to_backend()

        if self.planned_state_strategy in [
            PlannedStateStrategy.AUTO,
            PlannedStateStrategy.STRICT,
        ]:
            is_fresh = self.state_manager.is_planned_processing_state_fresh(
                planned_processing_state=available_planned_processing_state,
            )
            if not is_fresh:
                if self.planned_state_strategy == PlannedStateStrategy.STRICT:
                    raise StalePlannedStateException(
                        plan_state_uid=available_planned_processing_state.plan_state_uid,
                    )
                self.log_warn(
                    "Planned state is stale relative to the latest incremental "
                    "state; recomputing the processing state.",
                )
                self.compute_incremental_state()
                return

        self._use_planned_state(
            planned_processing_state=available_planned_processing_state,
        )

    def _use_planned_state(
        self,
        planned_processing_state: Any,
    ) -> None:
        """Execute from a planned processing state instead of recomputing.

        Assumes the latest incremental state has already been retrieved (the
        baseline is required to build the post-processing state on success).
        """
        self.state_manager.use_planned_processing_state(
            planned_processing_state=planned_processing_state,
        )
        self.log_info(
            f"Executing from planned state {planned_processing_state.plan_state_uid}.",
        )

        if self.state_manager.processing_state is not None:
            self.log_info(self.state_manager.processing_state.get_display_log())

        if (
            self.incremental_config is not None
            and self.incremental_config.persist_initial_processing_state
        ):
            self.persist_initial_processing_state()
            self._save_last_step_to_backend()

    def pre_processing_at_start(self) -> None:
        """Standard method, which is executed as the first call to run.

        Can be used to initialize some specific run variables."""

    def get_latest_execution_state(self) -> None:
        """Retrieve the latest execution state from the execution state manager."""
        self.state_manager.get_latest_execution_state()

    def compute_incremental_state(self, persist_to_backend: bool = True) -> None:
        """Compute the processing state for the next run.

        When applicable, this orchestrates:

        1. The retrieval of the latest incremental state.
        2. The retrieval of the source state (if pertinent).
        3. The determination of logically deleted entries (if pertinent).
        4. The determination of the processing state.
        5. The persistence of the initial processing state (if requested
           by ``incremental_config.persist_initial_processing_state``).

        Steps are skipped when the incremental definition flags disable them.

        Args:
            persist_to_backend: When True (default), the compute writes to the
                backends as a real run does: each computed step is persisted to
                the execution-history backend and the initial processing state
                is written to the live slot when the incremental config opts in.
                When False, the same compute steps run but every backend write is
                suppressed — used by the compute-only path that must not leave
                execution-history rows nor mutate the live processing-state slot.
        """
        definition = self.incremental_definition
        if not definition.tracks_state:
            return

        self.retrieve_latest_incremental_state()
        if persist_to_backend:
            self._save_last_step_to_backend()

        if definition.requires_source_state_retrieval:
            self.retrieve_source_state()
            if persist_to_backend:
                self._save_last_step_to_backend()

        if definition.tracks_logical_deletion:
            self.determine_logically_deleted_entries()
            if persist_to_backend:
                self._save_last_step_to_backend()

        self.determine_processing_state()
        if persist_to_backend:
            self._save_last_step_to_backend()

        if (
            persist_to_backend
            and self.incremental_config is not None
            and self.incremental_config.persist_initial_processing_state
        ):
            self.persist_initial_processing_state()
            self._save_last_step_to_backend()

    @track_flow_step(
        step_name="Pre-Processing For State - Retrieve Latest Incremental State",
        step_category=FlowStepCategory.PRE_PROCESSING_FOR_STATE,
    )
    def retrieve_latest_incremental_state(self) -> None:
        """Retrieve the latest incremental state from the execution state manager."""
        self.state_manager.get_latest_incremental_state()

    @track_flow_step(
        step_name="Pre-Processing For State - Retrieve Source State",
        step_category=FlowStepCategory.PRE_PROCESSING_FOR_STATE,
    )
    def retrieve_source_state(self) -> None:
        """
        Retrieve the source state.

        Can be customized based on the source state retrieval rules.
        """

    @track_flow_step(
        step_name="Pre-Processing For State - Determine logically deleted entries",
        step_category=FlowStepCategory.PRE_PROCESSING_FOR_STATE,
    )
    def determine_logically_deleted_entries(self) -> None:
        """
        Determine the logically deleted entries.
        """

    @track_flow_step(
        step_name="Pre-Processing For State - Determine processing state",
        step_category=FlowStepCategory.PRE_PROCESSING_FOR_STATE,
    )
    def determine_processing_state(self) -> None:
        """Determine processing state based on incremental and source state.

        Pure computation: builds the processing state in memory. Persistence
        to the live processing-state slot is handled by the separate
        ``persist_initial_processing_state`` step so future callers can
        reuse this method without writing to the live slot.
        """
        self.state_manager.init_processing_state()
        self.state_manager.update_processing_state()

        if self.state_manager.processing_state is not None:
            self.log_info(self.state_manager.processing_state.get_display_log())

    @track_flow_step(
        step_name="Pre-Processing For State - Persist initial processing state",
        step_category=FlowStepCategory.PRE_PROCESSING_FOR_STATE,
    )
    def persist_initial_processing_state(self) -> None:
        """Persist the freshly computed processing state to the live slot.

        Called by ``compute_incremental_state`` only when
        ``incremental_config.persist_initial_processing_state`` is True.
        Kept as its own step so the persistence side-effect is visible in
        the execution-history step list and so it can be skipped by callers
        that compute state without persisting.
        """
        self.state_manager.save_processing_state_start()

    # Post-processing methods
    def post_processing(self) -> None:
        """
        Execute all post-processing methods in sequence.

        This orchestrates post-processing for state, execution, and final cleanup.
        When partial state persistence was used during run_flow(), the bulk
        state save is skipped to preserve already-saved partial results.
        State post-processing is also skipped when disabled by the definition.
        """
        if (
            self.incremental_definition.tracks_state
            and not self.state_manager.was_partial_state_persistence_used()
        ):
            self.post_processing_for_state()
        self.post_processing_for_plan()
        self.post_processing_for_execution()
        self.post_processing_at_end()

    def post_processing_for_plan(self) -> None:
        """Mark a used planned state COMPLETED after a successful run.

        Leaves the plan PLANNED on failure so it can be re-run.
        """
        used_planned_processing_state = self.state_manager.used_planned_processing_state
        if used_planned_processing_state is None:
            return
        if (
            self.state_manager.current_execution_info.execution_status
            == FlowExecStatus.FAILED
        ):
            return
        self.state_manager.update_plan_state_to_completed(
            plan_state_uid=used_planned_processing_state.plan_state_uid,
            executed_by_flow_uid=self.flow_execution_info.flow_uid,
        )

    @track_flow_step(
        step_name="Post-Processing For State - Save Processed State",
        step_category=FlowStepCategory.POST_PROCESSING_FOR_STATE,
    )
    def _post_processing_for_state(self) -> None:
        """
        Save processed state and create post-processing state.

        This saves the processing state and creates/saves post-processing state.
        """
        self.state_manager.save_processed_state()
        self.state_manager.create_post_processing_state()
        self.state_manager.save_post_processing_state()

    def post_processing_for_state(self) -> None:
        """Execute post-processing for state and persist the step."""
        self._post_processing_for_state()
        self._save_last_step_to_backend()

    def post_processing_for_execution(self) -> None:
        """Update and save execution state on successful runs only."""
        if (
            self.state_manager.current_execution_info.execution_status
            == FlowExecStatus.FAILED
            or self.state_manager.data_load_strategy
            not in [
                FlowLoadingStrategies.FULL,
                FlowLoadingStrategies.DELTA,
                FlowLoadingStrategies.BACKFILL,
                FlowLoadingStrategies.BACKFILL_DELTA,
            ]
        ):
            return
        self.state_manager.update_global_execution_state()
        self.state_manager.save_all_execution_infos()

    def post_processing_at_end(self) -> None:
        """
        Standard method, which is executed as the last call of the run.

        Can be used to initialize some specific run variables.
        """

    # Logging and persistence helpers
    def _is_immediate_step_persistence_enabled(self) -> bool:
        """Check if steps should be saved immediately after completion."""
        if self.incremental_config is None:
            return True
        return self.incremental_config.immediate_step_persistence

    def _save_last_step_to_backend(self) -> None:
        """Persist the most recently appended step to the backend."""
        if (
            self._state_manager is not None
            and self._is_immediate_step_persistence_enabled()
            and self.flow_execution_info.steps
        ):
            self.state_manager.save_step_completed(
                step_info=self.flow_execution_info.steps[-1],
            )

    def run(self, **kwargs: Any) -> FlowExecutionInfo:
        """
        Execute the complete extraction workflow.

        Orchestrates pre-processing, flow execution, and post-processing.
        """
        self.pre_processing()
        self.state_manager.save_execution_start()

        flow_error: Exception | None = None
        try:
            self.run_flow()
            self.state_manager.update_execution_status_to_completed()
        except Exception as ex:
            flow_error = ex
            self.state_manager.update_execution_status_to_failed(
                error_message=str(ex),
            )

        self.post_processing()

        if flow_error is not None:
            raise flow_error
        return self.flow_execution_info
