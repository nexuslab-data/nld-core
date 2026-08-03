import abc
from abc import ABC
from typing import Any, ClassVar

from nld.connector.base.connector import DataConnector
from nld.exceptions import MissingMandatoryArgumentException
from nld.flow.definition.flow_definition import DataFlowDefinition
from nld.flow.execution.execution_info import (
    FlowExecutionHistory,
    FlowExecutionInfo,
    FlowExecutionState,
    FlowStepExecutionInfo,
)
from nld.flow.utils.flow_loading_strategy import FlowLoadingStrategies
from nld.parameters import (
    ExecutionParameterDefinition,
    apply_default_values_to_parameters,
)
from nld.utils.mixin import NldMixIn


def steps_from_loaded_executions(
    flow_uid: str,
    execution_state: FlowExecutionState,
    execution_history: FlowExecutionHistory,
) -> list[FlowStepExecutionInfo]:
    """Find the inline step list for ``flow_uid`` among already-read executions.

    Blob-based backends store each execution's steps inline in the state /
    history files, so resolving steps is a lookup over what
    ``retrieve_latest_execution_state`` already returned rather than a
    separate query.
    """
    for info in (execution_state.last_processed, *execution_history.executions):
        if info is not None and info.flow_uid == flow_uid:
            return list(info.steps or [])
    return []


class ExecutionBackendStateManager[DATA_CONNECTOR: DataConnector[Any]](NldMixIn, ABC):
    """Execution Backend State Manager.

    Manages all read and write methods for execution state.
    """

    param_definitions: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        backend_connector: DATA_CONNECTOR,
        flow_namespace: str,
        flow_name: str,
        parameters: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        super().__init__()
        self.backend_connector = backend_connector
        self.flow_namespace = flow_namespace
        self.flow_name = flow_name
        self.parameters = apply_default_values_to_parameters(
            parameters, self.get_param_definitions()
        )

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

    @classmethod
    def determine_parameters_for_flow_definition(
        cls,
        data_flow_definition: DataFlowDefinition | None,
    ) -> dict[str, Any]:
        """Derive backend parameters from the per-flow context.

        Receives the ``DataFlowDefinition`` so backend subclasses can pull
        whatever typed inputs they need from the flow being instantiated
        (target structure, predecessors, declared properties, ...) and
        translate them into backend parameter values like ``s3_root_path``.
        The factory merges the result with per-side
        ``ConnectorConfig.params`` and any explicit kwargs
        before validating against ``param_definitions``.

        The default implementation returns an empty dict so backends
        without per-flow derivation work unchanged.
        """
        return {}

    # Read-only accessor methods (used by `nld flow state` CLI).
    # The headers come from ``retrieve_latest_execution_state``; the steps
    # are then resolved per backend through ``_get_steps_for`` so the read
    # API behaves identically regardless of how a backend stores steps
    # (row-based backends join a dedicated step table; blob-based backends
    # return the steps already loaded inline on the info).
    @abc.abstractmethod
    def _get_steps_for(self, flow_uid: str) -> list[FlowStepExecutionInfo]:
        """Return the recorded steps for a single execution.

        Row-based backends query their step-history table filtered on
        ``flow_uid``; blob-based backends return the steps stored inline for
        that execution. Declared abstract so every backend must state how it
        reads steps — a backend that forgets would otherwise silently report
        "no steps".
        """
        raise NotImplementedError("'_get_steps_for' method is not yet implemented")

    def get_latest_execution_info(
        self, *, with_steps: bool = True
    ) -> FlowExecutionInfo | None:
        """Return the latest persisted FlowExecutionInfo for this flow.

        Read-only accessor used by tooling to inspect execution state without
        starting a flow run. Returns None when no execution has been recorded
        for the flow. When ``with_steps`` is False, the ``steps`` field is
        not populated — callers that only need the header avoid the extra
        step-history query.
        """
        execution_state, _ = self.retrieve_latest_execution_state()
        info = execution_state.last_processed
        if info is None:
            return None
        info.steps = self._get_steps_for(info.flow_uid) if with_steps else None
        return info

    def get_execution_info(
        self, flow_uid: str, *, with_steps: bool = True
    ) -> FlowExecutionInfo | None:
        """Return a single recorded execution by its ``flow_uid``.

        Read-only accessor used by tooling to inspect one execution
        without starting a flow run. Unlike ``get_execution_history`` this
        is never subject to any history listing limit: the full recorded
        history is scanned so an execution older than the most recent runs
        can still be inspected by uid. Returns None when no execution
        matches. When ``with_steps`` is False, the ``steps`` field is left
        empty.
        """
        _, history = self.retrieve_latest_execution_state()
        info = next(
            (i for i in history.executions if i.flow_uid == flow_uid),
            None,
        )
        if info is None:
            return None
        info.steps = self._get_steps_for(info.flow_uid) if with_steps else None
        return info

    def get_execution_history(
        self, *, limit: int | None = None, with_steps: bool = True
    ) -> FlowExecutionHistory:
        """Return the persisted execution history for this flow.

        Read-only accessor used by tooling to inspect execution history
        without starting a flow run. Results are ordered most recent first.
        When ``limit`` is provided, at most ``limit`` executions are returned.
        When ``with_steps`` is False, each entry's ``steps`` field is
        left empty — callers that only need the headers avoid the extra
        step-history queries.
        """
        _, history = self.retrieve_latest_execution_state()
        executions = sorted(
            history.executions,
            key=lambda info: info.started_at or "",
            reverse=True,
        )
        if limit is not None:
            executions = executions[:limit]
        for info in executions:
            info.steps = self._get_steps_for(info.flow_uid) if with_steps else None
        return FlowExecutionHistory(executions=executions)

    # Execution State methods
    @abc.abstractmethod
    def retrieve_latest_execution_state(
        self,
    ) -> tuple[FlowExecutionState, FlowExecutionHistory]:
        """Download the latest execution state.

        Returns:
            The tuple for the current execution state, with as first parameter
            the flow execution state and as second parameter the flow execution
            history.
        """
        raise NotImplementedError(
            "'retrieve_latest_execution_state' method is not yet implemented"
        )

    @abc.abstractmethod
    def save_execution_info(
        self,
        current_execution_info: FlowExecutionInfo,
        saved_step_names: list[str] | None = None,
    ) -> None:
        """
        Save the current execution info (header + steps) to the backend.

        For row-based backends (PostgreSQL, BigQuery, Snowflake, DuckDB,
        local-pydantic), persisting the current execution info as a new row
        intrinsically extends the execution history table; the separate
        ``save_execution_history_complete`` is therefore a no-op for them.
        For artifact-based backends (S3, local file outputs), this only
        writes the per-execution info file; the consolidated history file
        is rewritten separately by ``save_execution_history_complete``.

        Args:
            current_execution_info: Current execution information.
            saved_step_names: Step names already saved
                incrementally. These steps should be excluded from
                the save to avoid duplicates.
        """
        raise NotImplementedError("'save_execution_info' method is not yet implemented")

    def save_execution_history_complete(
        self,
        execution_history: FlowExecutionHistory,
    ) -> None:
        """Save the complete execution history as a single artifact.

        Default no-op: row-based backends already persist history through
        per-execution row inserts in ``save_execution_info``. Override on
        backends that store the history as a single consolidated artifact
        (e.g. S3 history file) and need an explicit full rewrite.
        """

    @abc.abstractmethod
    def save_execution_state(
        self,
        current_execution_info: FlowExecutionInfo | None = None,
        new_execution_state: FlowExecutionState | None = None,
    ) -> None:
        """
        Save the execution state record in the backend.

        Args:
            current_execution_info: Current execution information used as
                fallback when new_execution_state is not provided.
            new_execution_state: Execution state with carried-forward
                timestamps to save to the state table. When provided,
                its last_processed is used for the state record instead
                of current_execution_info.
        """
        raise NotImplementedError(
            "'save_execution_state' method is not yet implemented"
        )

    def save_execution_info_start(
        self,
        current_execution_info: FlowExecutionInfo,
    ) -> None:
        """Save execution info header at the start of execution.

        Default no-op. Override in subclasses that support
        incremental persistence.
        """

    def save_step_info(
        self,
        step_info: FlowStepExecutionInfo,
    ) -> None:
        """Save a single completed step to the backend.

        Default no-op. Override in subclasses that support
        incremental persistence.
        """

    def save_all_execution_infos(
        self,
        current_execution_info: FlowExecutionInfo,
        execution_history: FlowExecutionHistory,
        new_execution_state: FlowExecutionState | None = None,
        saved_step_names: list[str] | None = None,
        without_state: bool = False,
    ) -> None:
        """
        Save execution info and conditionally update the execution state.

        Execution history and step information are always saved.
        The execution state record is only updated when the loading
        strategy is not a pure backfill, so that backfill runs do
        not alter the global execution state.

        Args:
            current_execution_info: Current execution information.
            execution_history: Full execution history.
            new_execution_state: Execution state with carried-forward
                timestamps for the state table.
            saved_step_names: Step names already saved
                incrementally. These steps will be excluded from
                the final save to avoid duplicates.
            without_state: When True, never write the execution state
                record — used by failed executions.
        """
        self.save_execution_info(
            current_execution_info=current_execution_info,
            saved_step_names=saved_step_names,
        )
        self.save_execution_history_complete(execution_history=execution_history)
        if not without_state and current_execution_info.data_load_strategy in [
            FlowLoadingStrategies.FULL,
            FlowLoadingStrategies.DELTA,
            FlowLoadingStrategies.BACKFILL_DELTA,
        ]:
            self.save_execution_state(
                current_execution_info=current_execution_info,
                new_execution_state=new_execution_state,
            )


class ExecutionStateManager(NldMixIn):
    """Execution State Manager.

    Manages all the state operations and can operate with or without a backend
    state manager.
    """

    def __init__(
        self,
        current_execution_info: FlowExecutionInfo,
        execution_state_backend_manager: ExecutionBackendStateManager[Any]
        | None = None,
        secondary_execution_state_backend_manager: ExecutionBackendStateManager[Any]
        | None = None,
    ):
        super().__init__()

        # Current Execution info
        self.current_execution_info = current_execution_info

        # State backend manager
        self.execution_state_backend_manager = execution_state_backend_manager
        # Secondary backend mirrors execution info writes only.
        # Reads, history-complete writes and lifecycle ownership stay on primary.
        self.secondary_execution_state_backend_manager = (
            secondary_execution_state_backend_manager
        )

        # Execution State
        self.previous_execution_state: FlowExecutionState | None = None
        self.new_execution_state: FlowExecutionState | None = None
        self.execution_history: FlowExecutionHistory | None = None

        # Incremental persistence tracking
        self._saved_step_names: list[str] = []

    # Execution info methods
    @property
    def data_load_strategy(self) -> str:
        return self.current_execution_info.data_load_strategy

    # Execution State methods
    def get_latest_execution_state(self) -> None:
        """
        Retrieve the latest execution state from the backend.

        If no backend manager is configured, initializes default
        empty state and history.
        """
        if self.execution_state_backend_manager is not None:
            (
                self.previous_execution_state,
                self.execution_history,
            ) = self.execution_state_backend_manager.retrieve_latest_execution_state()
        else:
            self.previous_execution_state = FlowExecutionState()
            self.execution_history = FlowExecutionHistory(executions=[])

    def update_execution_status_to_completed(self, with_warning: bool = False) -> None:
        self.current_execution_info.update_execution_status_to_completed(
            with_warning=with_warning,
        )

    def update_execution_status_to_failed(
        self,
        error_message: str | None = None,
    ) -> None:
        self.current_execution_info.update_execution_status_to_failed(
            error_message=error_message,
        )

    def update_global_execution_state(self) -> None:
        """Updates the locally stored global execution state.

        Updates the execution state and the execution history.
        The history entry keeps the original execution info (truthful,
        may have None timestamps). The state's last_processed gets a
        copy with technical timestamps carried forward from the
        previous state when the current run returned None.

        For backfill runs the execution state is left unchanged so
        that the next regular run still sees the previous state.
        """
        assert self.current_execution_info.ended_at is not None, (
            "Update of the global execution state can be done only "
            "once the process is completed successfully"
        )
        if self.data_load_strategy != FlowLoadingStrategies.BACKFILL:
            self.new_execution_state = self.build_new_execution_state()
        if self.execution_history is None:
            self.execution_history = FlowExecutionHistory(
                executions=[self.current_execution_info],
            )
        else:
            self.execution_history.executions.append(self.current_execution_info)

    def build_new_execution_state(self) -> FlowExecutionState:
        """Build a new execution state with carried-forward timestamps.

        When technical timestamps are None on the current execution
        (e.g. no rows updated due to IS DISTINCT FROM optimization),
        the previous state's values are preserved so the next run
        still has access to the last known timestamps.
        """
        previous = (
            self.previous_execution_state.last_processed
            if self.previous_execution_state is not None
            else None
        )
        if previous is None:
            return FlowExecutionState(
                last_processed=self.current_execution_info,
            )

        current = self.current_execution_info
        previous_layer = (
            current.previous_layer_last_updated_at
            or previous.previous_layer_last_updated_at
        )
        source_extracted = current.source_extracted_at or previous.source_extracted_at
        source_updated = (
            current.source_last_updated_at or previous.source_last_updated_at
        )

        if (
            previous_layer == current.previous_layer_last_updated_at
            and source_extracted == current.source_extracted_at
            and source_updated == current.source_last_updated_at
        ):
            return FlowExecutionState(
                last_processed=current,
            )

        state_info = current.model_copy()
        state_info.previous_layer_last_updated_at = previous_layer
        state_info.source_extracted_at = source_extracted
        state_info.source_last_updated_at = source_updated
        return FlowExecutionState(
            last_processed=state_info,
        )

    def save_execution_start(self) -> None:
        """Save execution info header to backend at flow start."""
        if self.execution_state_backend_manager is not None:
            self.execution_state_backend_manager.save_execution_info_start(
                current_execution_info=self.current_execution_info,
            )
        if self.secondary_execution_state_backend_manager is not None:
            try:
                self.secondary_execution_state_backend_manager.save_execution_info_start(
                    current_execution_info=self.current_execution_info,
                )
            except Exception as exc:
                self.log_warn(
                    f"Secondary execution info start write failed "
                    f"(primary remains authoritative): {exc}",
                )

    def save_step_completed(
        self,
        step_info: FlowStepExecutionInfo,
    ) -> None:
        """Save a single step to backend after completion."""
        if self.execution_state_backend_manager is not None:
            self.execution_state_backend_manager.save_step_info(
                step_info=step_info,
            )
        if self.secondary_execution_state_backend_manager is not None:
            try:
                self.secondary_execution_state_backend_manager.save_step_info(
                    step_info=step_info,
                )
            except Exception as exc:
                self.log_warn(
                    f"Secondary execution step info write failed "
                    f"(primary remains authoritative): {exc}",
                )
        self._saved_step_names.append(step_info.step_name)

    def save_all_execution_infos(self, without_state: bool = False) -> None:
        """
        Save the execution state to the backend.

        If no backend manager is configured, this is a no-op.

        The current execution info and the execution state are mirrored to
        the secondary backend (when configured), but the consolidated
        execution history is NOT mirrored: the secondary backend only holds
        per-execution info, never the global history artifact.

        Args:
            without_state: When True, the execution state record that
                seeds the next incremental resume is not written — used
                by failed executions so their finalized header and steps
                still reach the history without advancing the state.
        """
        if self.execution_state_backend_manager is None:
            return
        assert self.execution_history is not None

        # Save execution info (header + steps) to primary and mirror to secondary.
        self.execution_state_backend_manager.save_execution_info(
            current_execution_info=self.current_execution_info,
            saved_step_names=self._saved_step_names,
        )
        if self.secondary_execution_state_backend_manager is not None:
            try:
                self.secondary_execution_state_backend_manager.save_execution_info(
                    current_execution_info=self.current_execution_info,
                    saved_step_names=self._saved_step_names,
                )
            except Exception as exc:
                self.log_warn(
                    f"Secondary execution info write failed "
                    f"(primary remains authoritative): {exc}",
                )

        # Save consolidated execution history on the primary only.
        self.execution_state_backend_manager.save_execution_history_complete(
            execution_history=self.execution_history,
        )

        # Save execution state (mirrored to secondary).
        if not without_state and self.current_execution_info.data_load_strategy in [
            FlowLoadingStrategies.FULL,
            FlowLoadingStrategies.DELTA,
            FlowLoadingStrategies.BACKFILL_DELTA,
        ]:
            self.execution_state_backend_manager.save_execution_state(
                current_execution_info=self.current_execution_info,
                new_execution_state=self.new_execution_state,
            )
            if self.secondary_execution_state_backend_manager is not None:
                try:
                    self.secondary_execution_state_backend_manager.save_execution_state(
                        current_execution_info=self.current_execution_info,
                        new_execution_state=self.new_execution_state,
                    )
                except Exception as exc:
                    self.log_warn(
                        f"Secondary execution state write failed "
                        f"(primary remains authoritative): {exc}",
                    )
