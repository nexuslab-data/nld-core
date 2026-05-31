"""Tasks backing the ``nld flow state`` CLI subcommands.

These tasks expose read-only access to the persisted execution and
incremental state of a data flow. They never mutate anything: no flow
runtime is started and no current execution is registered. They only
build the appropriate primary-backend state manager and call the
read-only accessors added on the backend managers.
"""

import json
import os
import sys
from collections.abc import Callable
from typing import Any, ClassVar

from nld.flow.definition.flow_definition import NamespacedDataFlowDefinition
from nld.flow.execution import FlowExecutionHistory, FlowExecutionInfo
from nld.flow.execution.factory import ExecutionStateManagerFactory
from nld.flow.incremental.models import (
    FlowIncrementalDefinition,
    FlowProcessingState,
    FlowState,
)
from nld.flow.incremental.services.factory import IncrementalStateManagerFactory
from nld.flow.state.state_backend_connector_resolver import (
    StateBackendConnectorWrapper,
    build_state_backend_connector_wrapper,
)
from nld.flow.task.data_flow_executor import (
    DataFlowExecutor,
)
from nld.flow.task.data_flow_state_renderers import (
    render_execution_history_text,
    render_execution_state_text,
    render_execution_steps_text,
    render_incremental_state_text,
    render_planned_processing_state_text,
    render_planned_processing_states_text,
    render_plans_not_supported_text,
    render_stateless_incremental_text,
)
from nld.parameters import ExecutionParameterDefinition
from nld.service import FileOutputService
from nld.task.base import StandardTask
from nld.utils.datetime_util import get_current_datetime
from nld.utils.requestor_utils import resolve_default_requestor

DISPLAY_FORMAT_TEXT = "text"
DISPLAY_FORMAT_JSON = "json"

FLOW_STATE_EXECUTION_GET_STATE_FILE_NAME = "flow_state_execution_get_state.json"
FLOW_STATE_EXECUTION_GET_HISTORY_FILE_NAME = "flow_state_execution_get_history.json"
FLOW_STATE_EXECUTION_GET_STEPS_FILE_NAME = "flow_state_execution_get_steps.json"
FLOW_STATE_INCREMENTAL_GET_STATE_FILE_NAME = "flow_state_incremental_get_state.json"
FLOW_STATE_INCREMENTAL_GET_PLANNED_FILE_NAME = "flow_state_incremental_get_planned.json"
FLOW_STATE_INCREMENTAL_COMPUTE_FILE_NAME = "flow_state_incremental_compute.json"


class AbstractDataFlowStateTask(StandardTask):
    """Common helpers for ``nld flow state`` tasks.

    Resolves the data flow definition from the project, validates that a
    ``state_backend_connector`` is configured, and exposes the primary
    state-backend connector through ``_get_primary_backend_connector``.

    Subclasses materialise their result data to a plain ``dict`` or ``list``
    (via Pydantic ``model_dump(mode="json")``) and call
    ``_persist_or_print`` with a fixed file name; that helper honours the
    ``output`` / ``override_output_folder_path`` convention shared with
    `BusinessDictionaryFindTask` and `DataFlowDependencyGraphTask`.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        "name",
        ExecutionParameterDefinition(name="namespace", mandatory=False),
        ExecutionParameterDefinition(name="profile_name", mandatory=False),
        ExecutionParameterDefinition(name="output", mandatory=False, data_type="bool"),
        ExecutionParameterDefinition(
            name="override_output_folder_path", mandatory=False
        ),
        ExecutionParameterDefinition(name="display_format", mandatory=False),
    ]

    def __init__(
        self,
        name: str,
        namespace: str | None = None,
        profile_name: str | None = None,
        output: bool = False,
        override_output_folder_path: str | None = None,
        display_format: str = DISPLAY_FORMAT_TEXT,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.flow_name_arg = name
        self.flow_namespace_arg = namespace
        self.profile_name = profile_name
        self.output = bool(output)
        self.override_output_folder_path = override_output_folder_path
        self.display_format = (display_format or DISPLAY_FORMAT_TEXT).lower()

        self.execution_context.load_entities()

        namespaced_data_flow_definition = (
            self.execution_context.entity_registry.get_data_flow_definition(
                entity_key=name,
                namespace=namespace,
            )
        )
        self.flow_namespace = namespaced_data_flow_definition.namespace
        self.data_flow_definition = namespaced_data_flow_definition.model

        self.data_flow_definition.load_task_module(
            namespace=self.flow_namespace,
            entity_path=self.execution_context.project.entity_path,
            additional_task_paths=(
                self.execution_context.project.flows_python_additional_paths
            ),
        )

        if self.data_flow_definition.state_backend_connector is None:
            raise RuntimeError(
                f"Flow '{name}' has no 'state_backend_connector' "
                "configured. State retrieval is not available for this flow."
            )

    def _build_state_backend_connector_wrapper(
        self,
    ) -> StateBackendConnectorWrapper:
        namespaced_data_flow_definition = NamespacedDataFlowDefinition(
            model=self.data_flow_definition,
            namespace=str(self.flow_namespace),
        )
        # __init__ guarantees state_backend_connector is configured, so the
        # resolver will return a non-None wrapper.
        state_backend_connector_wrapper = build_state_backend_connector_wrapper(
            namespaced_data_flow_definition=namespaced_data_flow_definition,
            execution_context=self.execution_context,
            open_connection=True,
            profile_name=self.profile_name,
        )
        assert state_backend_connector_wrapper is not None
        return state_backend_connector_wrapper

    def _build_execution_backend_manager(self) -> Any:
        state_backend_connector_wrapper = self._build_state_backend_connector_wrapper()
        return ExecutionStateManagerFactory().create_execution_backend_state_manager(
            state_backend_connector=state_backend_connector_wrapper.primary,
            flow_namespace=self.flow_namespace,
            flow_name=self.data_flow_definition.name,
            data_flow_definition=self.data_flow_definition,
        )

    def _get_incremental_definition(self) -> FlowIncrementalDefinition:
        """Return the flow's incremental definition (its capability flags).

        Cheap and connector-free: resolution is cached on the flow
        definition. Used to consult ``tracks_state`` before building a
        backend manager, so stateless strategies (e.g. ``no_increment``)
        can be answered without opening the state backend connector.
        """
        return self.data_flow_definition.resolve_incremental_logic().definition

    def _build_incremental_backend_manager(self) -> tuple[Any, str]:
        state_backend_connector_wrapper = self._build_state_backend_connector_wrapper()
        # Temporary: the registry is keyed by category until the
        # incremental-type identifier design is reworked. The proper
        # logical name vs. registry key separation will be addressed
        # in a follow-up.
        incremental_definition = (
            self.data_flow_definition.resolve_incremental_logic().definition
        )
        incremental_type = incremental_definition.category.lower()
        manager = (
            IncrementalStateManagerFactory().create_incremental_backend_state_manager(
                incremental_type=incremental_type,
                state_backend_connector=state_backend_connector_wrapper.primary,
                flow_namespace=self.flow_namespace,
                flow_name=self.data_flow_definition.name,
                data_flow_definition=self.data_flow_definition,
            )
        )
        return manager, incremental_type

    def _persist_or_print(
        self,
        *,
        data: dict[str, Any] | list[Any],
        file_name: str,
        text: str | None = None,
    ) -> None:
        """Write ``data`` either to a file (via FileOutputService) or stdout.

        Mirrors the convention used by `BusinessDictionaryFindTask`:
        ``--output`` and ``--override-output-folder-path`` switch from
        stdout to file output (always JSON for machine consumption);
        absent both, the payload is printed to stdout in either text
        (default) or JSON form depending on ``display_format``.

        Subclasses are responsible for materialising Pydantic models into
        plain dicts/lists via ``model_dump(mode="json")`` before calling
        this helper — `FileOutputService.write_json_file` only accepts
        `dict | list`.
        """
        if self.output or self.override_output_folder_path is not None:
            file_output_service = FileOutputService(
                root_folder_path=self.execution_context.get_nld_root_folder_path(),
                override_output_folder_path=self.override_output_folder_path,
            )
            file_output_service.write_json_file(
                file_name=file_name,
                data=data,
            )
            output_path = os.path.join(
                file_output_service.determine_output_folder_path(),
                file_name,
            )
            self.log_info(f"Wrote {file_name} to {output_path}")
            return

        if self.display_format == DISPLAY_FORMAT_TEXT and text is not None:
            sys.stdout.write(text)
            if not text.endswith("\n"):
                sys.stdout.write("\n")
        else:
            sys.stdout.write(
                json.dumps(data, indent=2, default=str, ensure_ascii=False) + "\n",
            )
        sys.stdout.flush()


class FlowStateExecutionGetStateTask(AbstractDataFlowStateTask):
    """``nld flow state execution get-state`` — latest execution as JSON."""

    def run(self, **kwargs: Any) -> bool:
        backend_manager = self._build_execution_backend_manager()
        # Skip the step-history join entirely — get-state returns the
        # header only; the dedicated ``get-steps`` subcommand is the way
        # to retrieve step detail. ``exclude_none`` drops null fields so
        # the payload only carries set values.
        info: FlowExecutionInfo | None = backend_manager.get_latest_execution_info(
            with_steps=False,
        )
        data: dict[str, Any] = (
            info.model_dump(mode="json", exclude={"steps"}, exclude_none=True)
            if info is not None
            else {}
        )
        self._persist_or_print(
            data=data,
            file_name=FLOW_STATE_EXECUTION_GET_STATE_FILE_NAME,
            text=render_execution_state_text(info),
        )
        return True


class FlowStateExecutionGetHistoryTask(AbstractDataFlowStateTask):
    """``nld flow state execution get-history`` — execution history as JSON."""

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        *AbstractDataFlowStateTask.init_params,
        ExecutionParameterDefinition(name="limit", mandatory=False, data_type="int"),
    ]

    def __init__(
        self,
        name: str,
        namespace: str | None = None,
        output: bool = False,
        override_output_folder_path: str | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            name=name,
            namespace=namespace,
            output=output,
            override_output_folder_path=override_output_folder_path,
            **kwargs,
        )
        self.limit = limit

    def run(self, **kwargs: Any) -> bool:
        backend_manager = self._build_execution_backend_manager()
        history: FlowExecutionHistory = backend_manager.get_execution_history(
            limit=self.limit,
        )
        self._persist_or_print(
            data=history.model_dump(mode="json", exclude_none=True),
            file_name=FLOW_STATE_EXECUTION_GET_HISTORY_FILE_NAME,
            text=render_execution_history_text(history),
        )
        return True


class FlowStateExecutionGetStepsTask(AbstractDataFlowStateTask):
    """``nld flow state execution get-steps`` — step list of one execution.

    Selects the execution via either ``--flow-uid <UID>`` or ``--latest``.
    The two flags are mutually exclusive and exactly one is required;
    enforcement happens in the CLI layer before this task is constructed.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        *AbstractDataFlowStateTask.init_params,
        ExecutionParameterDefinition(name="flow_uid", mandatory=False),
        ExecutionParameterDefinition(name="latest", mandatory=False, data_type="bool"),
    ]

    def __init__(
        self,
        name: str,
        namespace: str | None = None,
        output: bool = False,
        override_output_folder_path: str | None = None,
        flow_uid: str | None = None,
        latest: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            name=name,
            namespace=namespace,
            output=output,
            override_output_folder_path=override_output_folder_path,
            **kwargs,
        )
        self.flow_uid = flow_uid
        self.latest = bool(latest)
        if self.flow_uid is None and not self.latest:
            raise ValueError(
                "FlowStateExecutionGetStepsTask requires either 'flow_uid' "
                "or 'latest' to be set."
            )
        if self.flow_uid is not None and self.latest:
            raise ValueError(
                "FlowStateExecutionGetStepsTask: 'flow_uid' and 'latest' "
                "are mutually exclusive."
            )

    def run(self, **kwargs: Any) -> bool:
        backend_manager = self._build_execution_backend_manager()

        info: FlowExecutionInfo | None
        if self.latest:
            # Read from history rather than the execution-state table:
            # the state table is only updated for FULL/DELTA/BACKFILL_DELTA
            # strategies, so a BACKFILL-only flow would otherwise yield [].
            history = backend_manager.get_execution_history(limit=1)
            info = history.executions[0] if history.executions else None
        else:
            history = backend_manager.get_execution_history()
            info = next(
                (i for i in history.executions if i.flow_uid == self.flow_uid),
                None,
            )

        steps = list(info.steps or []) if info is not None else []
        self._persist_or_print(
            data=[s.model_dump(mode="json", exclude_none=True) for s in steps],
            file_name=FLOW_STATE_EXECUTION_GET_STEPS_FILE_NAME,
            text=render_execution_steps_text(steps),
        )
        return True


class FlowStateIncrementalGetStateTask(AbstractDataFlowStateTask):
    """``nld flow state incremental get-state`` — incremental state as JSON.

    By default returns only the current processing state. With
    ``--include-post-processing`` returns an object that bundles both the
    processing state and the post-processing (authoritative) state.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        *AbstractDataFlowStateTask.init_params,
        ExecutionParameterDefinition(
            name="include_post_processing", mandatory=False, data_type="bool"
        ),
    ]

    def __init__(
        self,
        name: str,
        namespace: str | None = None,
        output: bool = False,
        override_output_folder_path: str | None = None,
        include_post_processing: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            name=name,
            namespace=namespace,
            output=output,
            override_output_folder_path=override_output_folder_path,
            **kwargs,
        )
        self.include_post_processing = bool(include_post_processing)

    def run(self, **kwargs: Any) -> bool:
        definition = self._get_incremental_definition()
        # Stateless strategies (tracks_state=False, e.g. no_increment for
        # VIEW flows) never record incremental state, so report that
        # plainly instead of letting the backend read raise.
        if not definition.tracks_state:
            self._persist_or_print(
                data={},
                file_name=FLOW_STATE_INCREMENTAL_GET_STATE_FILE_NAME,
                text=render_stateless_incremental_text(strategy=definition.category),
            )
            return True

        backend_manager, _ = self._build_incremental_backend_manager()

        processing: FlowProcessingState | None = backend_manager.read_processing_state()

        if not self.include_post_processing:
            self._persist_or_print(
                data=processing.model_dump(mode="json", exclude_none=True)
                if processing is not None
                else {},
                file_name=FLOW_STATE_INCREMENTAL_GET_STATE_FILE_NAME,
                text=render_incremental_state_text(
                    processing=processing,
                    post_processing=None,
                    include_post_processing=False,
                ),
            )
            return True

        post_processing: FlowState | None = backend_manager.read_post_processing_state()
        # Drop both per-state nulls (via ``exclude_none``) and the
        # top-level wrapper entries when the underlying state is missing
        # entirely, so the payload only carries set values.
        data: dict[str, Any] = {}
        if processing is not None:
            data["processing_state"] = processing.model_dump(
                mode="json", exclude_none=True
            )
        if post_processing is not None:
            data["post_processing_state"] = post_processing.model_dump(
                mode="json", exclude_none=True
            )
        self._persist_or_print(
            data=data,
            file_name=FLOW_STATE_INCREMENTAL_GET_STATE_FILE_NAME,
            text=render_incremental_state_text(
                processing=processing,
                post_processing=post_processing,
                include_post_processing=True,
            ),
        )
        return True


class FlowStateIncrementalGetPlannedTask(AbstractDataFlowStateTask):
    """``nld flow state incremental get-planned`` — list PLANNED plans as JSON.

    Returns every plan in ``PLANNED`` status for the flow (newest first),
    carrying the lifecycle metadata of each state plan. The
    strategy-specific processing-state payload of a single plan is read
    through ``get-state``, not this listing.
    """

    def run(self, **kwargs: Any) -> bool:
        definition = self._get_incremental_definition()
        # Plans only exist for strategies that opt into planned-state
        # support; one that disables it (supports_planned_state=False, e.g.
        # no_increment) never persists a plan, so report that plainly
        # instead of letting the backend read raise.
        if not definition.supports_planned_state:
            self._persist_or_print(
                data=[],
                file_name=FLOW_STATE_INCREMENTAL_GET_PLANNED_FILE_NAME,
                text=render_plans_not_supported_text(strategy=definition.category),
            )
            return True

        backend_manager, _ = self._build_incremental_backend_manager()
        # The definition supports plans, but the configured state backend
        # may still be unable to hold one (e.g. DuckDB); report that plainly
        # instead of letting ``read_planned_processing_states`` raise.
        if not backend_manager.supports_planned_state:
            self._persist_or_print(
                data=[],
                file_name=FLOW_STATE_INCREMENTAL_GET_PLANNED_FILE_NAME,
                text=render_plans_not_supported_text(strategy=definition.category),
            )
            return True
        plans = backend_manager.read_planned_processing_states()
        self._persist_or_print(
            data=[plan.model_dump(mode="json", exclude_none=True) for plan in plans],
            file_name=FLOW_STATE_INCREMENTAL_GET_PLANNED_FILE_NAME,
            text=render_planned_processing_states_text(plans=plans),
        )
        return True


class FlowStateIncrementalComputeTask(AbstractDataFlowStateTask):
    """``nld flow state incremental compute`` — compute the next processing state.

    Drives the same ``compute_incremental_state`` slice that a real run
    would execute, but never starts a flow run, never writes the live
    processing-state slot, and never writes execution-history rows.

    When ``persist`` is True, the computed processing state is persisted
    via ``state_manager.save_planned_processing_state`` as a new
    ``PLANNED`` plan, cancelling any prior ``PLANNED`` plan for the same
    flow on the primary state backend.

    Source-side queries (``retrieve_source_state``) can be expensive and
    visible on the source side. The task gates that step on the user's
    explicit authorization via ``source_request_authorized``. When the
    incremental definition declares ``requires_source_state_retrieval``
    and the flag is False, the task delegates the prompt to the
    ``confirm_source_request`` callback injected at construction time by
    the caller. When no callback is provided and the flag is False, the
    task refuses to run — keeping the task itself free of any
    presentation-layer dependency.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        *AbstractDataFlowStateTask.init_params,
        ExecutionParameterDefinition(
            name="persist",
            mandatory=False,
            data_type="bool",
        ),
        ExecutionParameterDefinition(
            name="requestor",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="source_request_authorized",
            mandatory=False,
            data_type="bool",
        ),
    ]

    def __init__(
        self,
        name: str,
        namespace: str | None = None,
        output: bool = False,
        override_output_folder_path: str | None = None,
        persist: bool = False,
        requestor: str | None = None,
        source_request_authorized: bool = False,
        confirm_source_request: Callable[[str], bool] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            name=name,
            namespace=namespace,
            output=output,
            override_output_folder_path=override_output_folder_path,
            **kwargs,
        )
        self.persist = bool(persist)
        self.requestor = requestor or resolve_default_requestor()
        self.source_request_authorized = bool(source_request_authorized)
        self.confirm_source_request = confirm_source_request

        # Reuse the executor to build a fully-initialised DataFlowTask
        # (with the state manager) — zero duplication of the connector
        # and init-params plumbing. The task forwards its own already
        # parsed parameter dict instead of re-parsing the process
        # arguments, which the incremental argparser would reject because
        # it does not recognise the state-subcommand path.
        namespaced_data_flow_definition = NamespacedDataFlowDefinition(
            model=self.data_flow_definition,
            namespace=str(self.flow_namespace),
        )
        self._executor = DataFlowExecutor(
            namespaced_data_flow_definition=namespaced_data_flow_definition,
            params=self.execution_context.task_request.get_parameters(),
        )
        self._data_flow_task = self._executor.init_data_flow_task(
            connections_should_be_opened=True,
        )

    def _needs_source_confirmation(self) -> bool:
        definition = self._data_flow_task.incremental_definition
        return bool(
            definition.requires_source_state_retrieval
            and not self.source_request_authorized,
        )

    def _confirmation_message(self) -> str:
        return (
            f"Computing the incremental state for flow "
            f"'{self.flow_namespace}/{self.data_flow_definition.name}' "
            f"will issue source-side queries via the flow's own "
            f"``retrieve_source_state`` step. Proceed?"
        )

    def run(self, **kwargs: Any) -> bool:
        if self._needs_source_confirmation():
            if self.confirm_source_request is None:
                self.log_info(
                    "Source-state retrieval not authorized: pass "
                    "--source-request-authorized or inject a "
                    "``confirm_source_request`` callback. Cancelled.",
                )
                return False
            if not self.confirm_source_request(self._confirmation_message()):
                self.log_info("Compute cancelled by user.")
                return False

        # Compute the next processing state without writing execution-
        # history step rows or the live processing-state slot.
        self._data_flow_task.compute_incremental_state(
            persist_to_backend=False,
        )
        processing_state = self._data_flow_task.state_manager.processing_state

        plan_state_uid: str | None = None
        # Plans require both the incremental definition to support them and
        # the state backend to be able to hold one; either off means a plan
        # the execute path would never consume, so refuse to persist it.
        supports_planned_state = (
            self._data_flow_task.incremental_definition.supports_planned_state
            and self._data_flow_task.state_manager.backend_supports_planned_state
        )
        if self.persist and not supports_planned_state:
            self.log_info(
                f"Planned states are not supported for strategy "
                f"'{self._data_flow_task.incremental_definition.category}'; "
                f"the computed state will not be persisted.",
            )
        if self.persist and supports_planned_state and processing_state is not None:
            # Reuse the execution UUID generated for this compute run as
            # the plan identifier instead of minting a fresh one.
            plan_state_uid = self._data_flow_task.exec_uuid
            self.log_info(
                f"Persisting plan {plan_state_uid} (requestor={self.requestor!r}).",
            )
            self._data_flow_task.state_manager.save_planned_processing_state(
                processing_flow_state=processing_state,
                plan_state_uid=plan_state_uid,
                computed_at=get_current_datetime(),
                requestor=self.requestor,
            )

        data: dict[str, Any] = {}
        if processing_state is not None:
            data["processing_state"] = processing_state.model_dump(
                mode="json",
                exclude_none=True,
            )
        if plan_state_uid is not None:
            data["plan_state_uid"] = plan_state_uid
            data["persisted"] = True
            data["requestor"] = self.requestor
        else:
            data["persisted"] = False

        self._persist_or_print(
            data=data,
            file_name=FLOW_STATE_INCREMENTAL_COMPUTE_FILE_NAME,
            text=render_planned_processing_state_text(
                processing=processing_state,
                persisted=plan_state_uid is not None,
                plan_state_uid=plan_state_uid,
                requestor=self.requestor,
            ),
        )
        return True
