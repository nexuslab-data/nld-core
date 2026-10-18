import datetime
from typing import Any, cast

from nld.connector.base.connector import SQLDataConnector
from nld.docs.models import ProjectSnapshot
from nld.docs.state.errors import categorise_backend_error
from nld.docs.state.models import (
    SLA_STATUS_FAILED,
    SLA_STATUS_LATE,
    SLA_STATUS_NEVER_RUN,
    SLA_STATUS_ON_TIME,
    SLA_STATUS_RUNNING,
    SLA_STATUS_UNKNOWN,
    STATE_STATUS_OK,
    STATE_STATUS_UNAVAILABLE,
    DocsBackendState,
    DocsFlowDeploymentState,
    DocsFlowExecutionState,
    DocsFlowSlaState,
    DocsLiveState,
    DocsStateSection,
    DocsStructureDeploymentState,
    DocsStructureFreshnessState,
)
from nld.flow.deploy import (
    FlowDeployMetadataManager,
    compute_flow_yaml_hash,
)
from nld.flow.execution import ExecutionStateManagerFactory
from nld.flow.state.state_backend_connector_resolver import (
    build_effective_state_backend_connector_config_wrapper,
    build_state_backend_connector_wrapper,
)
from nld.flow.utils.flow_execution_params import FlowExecStatus
from nld.pydantic import NldNamespace
from nld.scheduling import ExecutionFrequency
from nld.service import EntityTypeNames
from nld.structure.deploy import (
    StructureMetadataBackendManager,
    compute_structure_hash,
)
from nld.task.context import NldExecutionContext

SLA_TOLERANCE_RATIO: float = 1.5

EXECUTION_SUCCESS_STATUSES: frozenset[str] = frozenset(
    {
        FlowExecStatus.SUCCEEDED.value,
        FlowExecStatus.SUCCEEDED_WITH_WARNING.value,
    }
)

NO_EXECUTION_MESSAGE: str = "No execution recorded yet."


def _split_entity_id(entity_id: str) -> tuple[str, str]:
    """Split ``namespace.name`` into its two parts, root namespace aware."""
    namespace, separator, name = entity_id.rpartition(".")
    if not separator:
        return NldNamespace.ROOT_VALUE, entity_id
    return namespace, name


def _age_seconds(
    moment: datetime.datetime | None,
    now: datetime.datetime,
) -> float | None:
    """Return the age of a timestamp in seconds, naive timestamps included."""
    if moment is None:
        return None
    reference = now if moment.tzinfo is not None else now.replace(tzinfo=None)
    return (reference - moment).total_seconds()


def expected_interval_seconds(frequency_value: str | None) -> int | None:
    """Return the cadence interval a declared frequency implies, if any."""
    if frequency_value is None:
        return None
    try:
        frequency = ExecutionFrequency(frequency_value)
    except ValueError:
        return None
    return frequency.expected_interval_seconds


class LiveStateCollector:
    """Reads the running system's state for the docs UI.

    Every read is best effort: a section that cannot be reached reports
    itself unavailable with the reason, and the UI keeps rendering the
    repository-only view.
    """

    def __init__(
        self,
        execution_context: NldExecutionContext,
        snapshot: ProjectSnapshot,
        environment: str | None = None,
    ) -> None:
        self.execution_context = execution_context
        self.snapshot = snapshot
        self.environment = environment
        self._unreachable_connectors: dict[str, str] = {}

    def collect(self) -> DocsLiveState:
        """Collect every state section, never raising on a backend failure.

        The server answers from a request thread where the execution context
        variable is not set, and the connector resolution requires it: the
        collector enters its own context when none is current.
        """
        if NldExecutionContext.get_current() is not None:
            return self._collect()
        with self.execution_context:
            return self._collect()

    def _collect(self) -> DocsLiveState:
        """Collect every section, with the execution context set."""
        self._unreachable_connectors = {}
        now = datetime.datetime.now(tz=datetime.UTC)
        state = DocsLiveState(
            collected_at=now,
            environment=self.environment,
        )

        metadata_connector = self._collect_backend(state=state)
        if metadata_connector is not None:
            self._collect_deployments(
                state=state,
                metadata_connector=metadata_connector,
            )

        self._collect_executions(
            state=state,
            now=now,
        )
        state.available = (
            state.backend.section.status == STATE_STATUS_OK
            or state.execution_section.status == STATE_STATUS_OK
        )
        if not state.available:
            state.message = (
                "No backend could be reached; the project view below is built "
                "from the repository alone."
            )
        return state

    def _collect_backend(
        self,
        state: DocsLiveState,
    ) -> SQLDataConnector[Any] | None:
        """Open the metadata backend declared by the project, if any."""
        connection_name = self.snapshot.project.metadata_backend_connector
        if connection_name is None:
            state.backend = DocsBackendState(
                section=DocsStateSection(
                    status=STATE_STATUS_UNAVAILABLE,
                    message=(
                        "The project declares no metadata_backend_connector, so "
                        "no deployment state can be read."
                    ),
                ),
            )
            return None

        try:
            connector = cast(
                "SQLDataConnector[Any]",
                self.execution_context.get_data_connector(
                    name=connection_name,
                    open_connection=True,
                ),
            )
            metadata_schema = connector.get_active_schema()
        except Exception as error:  # noqa: BLE001 - every backend failure degrades
            message = categorise_backend_error(error=error)
            self._unreachable_connectors[connection_name] = message
            state.backend = DocsBackendState(
                section=DocsStateSection(
                    status=STATE_STATUS_UNAVAILABLE,
                    message=message,
                ),
                connection_name=connection_name,
            )
            return None

        state.backend = DocsBackendState(
            section=DocsStateSection(status=STATE_STATUS_OK),
            connection_name=connection_name,
            connector_type=self._connector_type(connection_name=connection_name),
            metadata_schema=metadata_schema,
        )
        if metadata_schema is None:
            state.backend.section = DocsStateSection(
                status=STATE_STATUS_UNAVAILABLE,
                message=(
                    "The metadata backend connection has no schema configured, "
                    "so its tables cannot be located."
                ),
            )
            return None
        return connector

    def _connector_type(
        self,
        connection_name: str,
    ) -> str | None:
        """Return the declared type of a connection, from the snapshot."""
        for connection in self.snapshot.project.connections:
            if connection.name == connection_name:
                return connection.connector_type
        return None

    def _collect_deployments(
        self,
        state: DocsLiveState,
        metadata_connector: SQLDataConnector[Any],
    ) -> None:
        """Compare what is deployed with what the repository declares."""
        metadata_schema = state.backend.metadata_schema
        if metadata_schema is None:
            return

        try:
            structure_manager = StructureMetadataBackendManager(
                metadata_connector=metadata_connector,
            )
            structure_rows = structure_manager.read_all_state_rows(
                metadata_schema=metadata_schema,
            )
            flow_manager = FlowDeployMetadataManager(
                connector=metadata_connector,
            )
            flow_rows = flow_manager.get_all_deployed_flows(
                metadata_schema=metadata_schema,
            )
        except Exception as error:  # noqa: BLE001 - a missing table degrades too
            state.deployment_section = DocsStateSection(
                status=STATE_STATUS_UNAVAILABLE,
                message=categorise_backend_error(error=error),
            )
            return

        registry = self.execution_context.entity_registry
        structure_states: list[DocsStructureDeploymentState] = []
        for structure_summary in self.snapshot.structures:
            namespaced = registry.get_structure(
                entity_key=structure_summary.entity_key,
                namespace=structure_summary.namespace,
            )
            repository_hash = compute_structure_hash(structure=namespaced.model)
            row = structure_rows.get(
                (structure_summary.namespace, structure_summary.name)
            )
            structure_states.append(
                DocsStructureDeploymentState(
                    structure_id=structure_summary.node_id,
                    namespace=structure_summary.namespace,
                    structure_name=structure_summary.name,
                    deployed_at=row.deployed_at if row is not None else None,
                    deployment_id=row.deployment_id if row is not None else None,
                    deployed_hash=row.structure_hash if row is not None else None,
                    repository_hash=repository_hash,
                    drift=(row is not None and row.structure_hash != repository_hash),
                    deployed=row is not None,
                )
            )

        flow_states: list[DocsFlowDeploymentState] = []
        for flow_summary in self.snapshot.flows:
            namespaced_flow = registry.get_data_flow_definition(
                entity_key=flow_summary.entity_key,
                namespace=flow_summary.namespace,
            )
            repository_hash = compute_flow_yaml_hash(
                flow_definition=namespaced_flow.model,
            )
            row_flow = flow_rows.get(flow_summary.node_id)
            flow_states.append(
                DocsFlowDeploymentState(
                    flow_id=flow_summary.node_id,
                    namespace=flow_summary.namespace,
                    flow_name=flow_summary.name,
                    deployed_at=row_flow.deployed_at if row_flow is not None else None,
                    deployment_id=(
                        row_flow.deployment_id if row_flow is not None else None
                    ),
                    deployed_yaml_hash=(
                        row_flow.flow_yaml_hash if row_flow is not None else None
                    ),
                    repository_yaml_hash=repository_hash,
                    drift=(
                        row_flow is not None
                        and row_flow.flow_yaml_hash != repository_hash
                    ),
                    deployed=row_flow is not None,
                )
            )

        state.structure_deployments = structure_states
        state.flow_deployments = flow_states
        state.deployment_section = DocsStateSection(status=STATE_STATUS_OK)

    def _collect_executions(
        self,
        state: DocsLiveState,
        now: datetime.datetime,
    ) -> None:
        """Read the latest execution of every flow that tracks its state."""
        registry = self.execution_context.entity_registry
        registry_loaded = EntityTypeNames.DATA_FLOW_DEFINITION in registry.entities
        if not registry_loaded:
            state.execution_section = DocsStateSection(
                status=STATE_STATUS_UNAVAILABLE,
                message="No flow definition is loaded.",
            )
            return

        executions: list[DocsFlowExecutionState] = []
        reached_any = False
        for flow_summary in self.snapshot.flows:
            namespaced_flow = registry.get_data_flow_definition(
                entity_key=flow_summary.entity_key,
                namespace=flow_summary.namespace,
            )
            config_wrapper = build_effective_state_backend_connector_config_wrapper(
                namespaced_data_flow_definition=namespaced_flow,
                execution_context=self.execution_context,
            )
            if config_wrapper is None:
                continue

            # A connector that already refused one flow refuses them all:
            # retrying it per flow multiplies one timeout by the flow count.
            connector_name = config_wrapper.primary.connector
            cached_failure = self._unreachable_connectors.get(connector_name)
            if cached_failure is not None:
                executions.append(
                    DocsFlowExecutionState(
                        flow_id=flow_summary.node_id,
                        reached=False,
                        message=cached_failure,
                    )
                )
                continue

            try:
                wrapper = build_state_backend_connector_wrapper(
                    namespaced_data_flow_definition=namespaced_flow,
                    execution_context=self.execution_context,
                    open_connection=True,
                )
            except Exception as error:  # noqa: BLE001 - the connector is down
                message = categorise_backend_error(error=error)
                self._unreachable_connectors[connector_name] = message
                executions.append(
                    DocsFlowExecutionState(
                        flow_id=flow_summary.node_id,
                        reached=False,
                        message=message,
                    )
                )
                continue
            if wrapper is None:
                continue

            try:
                factory = ExecutionStateManagerFactory()
                manager = factory.create_execution_backend_state_manager(
                    state_backend_connector=wrapper.primary,
                    flow_namespace=namespaced_flow.namespace,
                    flow_name=namespaced_flow.model.name,
                    data_flow_definition=namespaced_flow.model,
                )
                info = manager.get_latest_execution_info(with_steps=True)
            except Exception as error:  # noqa: BLE001 - one flow must not break all
                executions.append(
                    DocsFlowExecutionState(
                        flow_id=flow_summary.node_id,
                        reached=False,
                        message=categorise_backend_error(error=error),
                    )
                )
                continue

            reached_any = True
            if info is None:
                executions.append(
                    DocsFlowExecutionState(
                        flow_id=flow_summary.node_id,
                        reached=True,
                        message=NO_EXECUTION_MESSAGE,
                    )
                )
                continue

            executions.append(
                DocsFlowExecutionState(
                    flow_id=flow_summary.node_id,
                    reached=True,
                    flow_uid=info.flow_uid,
                    execution_status=info.execution_status,
                    started_at=info.started_at,
                    ended_at=info.ended_at,
                    duration_seconds=(
                        (info.ended_at - info.started_at).total_seconds()
                        if info.started_at is not None and info.ended_at is not None
                        else None
                    ),
                    execution_error=info.execution_error,
                    source_last_updated_at=info.source_last_updated_at,
                    previous_layer_last_updated_at=(
                        info.previous_layer_last_updated_at
                    ),
                    steps=[
                        step.model_dump(mode="json", exclude_none=True)
                        for step in getattr(info, "steps", []) or []
                    ],
                )
            )

        state.executions = executions
        state.execution_section = DocsStateSection(
            status=STATE_STATUS_OK if reached_any else STATE_STATUS_UNAVAILABLE,
            message=(
                None if reached_any else "No flow state backend could be reached."
            ),
        )
        state.sla = self._build_sla(
            executions=executions,
            now=now,
        )
        state.freshness = self._build_freshness(
            executions=executions,
            now=now,
        )

    def _build_sla(
        self,
        executions: list[DocsFlowExecutionState],
        now: datetime.datetime,
    ) -> list[DocsFlowSlaState]:
        """Compare each flow's declared cadence with its last successful run."""
        execution_by_flow = {execution.flow_id: execution for execution in executions}
        sla_states: list[DocsFlowSlaState] = []

        for flow_summary in self.snapshot.flows:
            for schedule in flow_summary.schedules or []:
                if self.environment is not None and (
                    schedule.environment != self.environment
                ):
                    continue
                frequency_value = (
                    str(schedule.frequency.get("value"))
                    if schedule.frequency is not None
                    else None
                )
                expected = expected_interval_seconds(frequency_value=frequency_value)
                execution = execution_by_flow.get(flow_summary.node_id)
                last_status = (
                    execution.execution_status if execution is not None else None
                )
                last_success = (
                    execution.ended_at
                    if execution is not None
                    and last_status is not None
                    and last_status.upper() in EXECUTION_SUCCESS_STATUSES
                    else None
                )
                age = _age_seconds(
                    moment=last_success,
                    now=now,
                )
                sla_states.append(
                    DocsFlowSlaState(
                        flow_id=flow_summary.node_id,
                        environment=schedule.environment,
                        frequency=frequency_value,
                        expected_interval_seconds=expected,
                        tolerance_ratio=SLA_TOLERANCE_RATIO,
                        last_success_at=last_success,
                        last_status=last_status,
                        age_seconds=age,
                        status=self._sla_status(
                            expected=expected,
                            age=age,
                            execution=execution,
                        ),
                    )
                )

        return sla_states

    @staticmethod
    def _sla_status(
        expected: int | None,
        age: float | None,
        execution: DocsFlowExecutionState | None,
    ) -> str:
        """Classify a flow against its declared cadence.

        The latest record decides: a failed or still running latest attempt
        is reported as such rather than as "never run", and a backend that
        could not be read yields "unknown" instead of a verdict.
        """
        if execution is None or not execution.reached:
            return SLA_STATUS_UNKNOWN
        status = (execution.execution_status or "").upper()
        if not status:
            return SLA_STATUS_NEVER_RUN
        if status == FlowExecStatus.FAILED.value:
            return SLA_STATUS_FAILED
        if status == FlowExecStatus.ON_GOING.value:
            return SLA_STATUS_RUNNING
        if age is None or expected is None:
            return SLA_STATUS_UNKNOWN
        if age <= expected * SLA_TOLERANCE_RATIO:
            return SLA_STATUS_ON_TIME
        return SLA_STATUS_LATE

    def _build_freshness(
        self,
        executions: list[DocsFlowExecutionState],
        now: datetime.datetime,
    ) -> list[DocsStructureFreshnessState]:
        """Derive each target structure's data age from its producing flow."""
        execution_by_flow = {execution.flow_id: execution for execution in executions}
        freshness: list[DocsStructureFreshnessState] = []

        for structure_summary in self.snapshot.structures:
            for producing_flow in structure_summary.produced_by:
                execution = execution_by_flow.get(producing_flow)
                if execution is None:
                    continue
                last_updated = (
                    execution.source_last_updated_at
                    or execution.previous_layer_last_updated_at
                    or execution.ended_at
                )
                source = (
                    "source_last_updated_at"
                    if execution.source_last_updated_at is not None
                    else (
                        "previous_layer_last_updated_at"
                        if execution.previous_layer_last_updated_at is not None
                        else "ended_at"
                    )
                )
                freshness.append(
                    DocsStructureFreshnessState(
                        structure_id=structure_summary.node_id,
                        last_updated_at=last_updated,
                        age_seconds=_age_seconds(
                            moment=last_updated,
                            now=now,
                        ),
                        source=source,
                        produced_by=producing_flow,
                    )
                )

        return freshness
