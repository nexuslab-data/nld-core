from typing import Any, ClassVar

from nld.flow.definition import NamespacedDataFlowDefinition
from nld.flow.execution import FlowExecutionInfo, FlowExecutionInfoWrapper
from nld.flow.graph import FLOW_NODE_TYPE, DataFlowGraph, strip_node_type_prefix
from nld.flow.incremental.models import PlannedStateStrategy
from nld.flow.sql.task.sql_rendering_executor import SQLRenderingExecutor
from nld.flow.utils import FlowExecStatus, FlowUpdateStrategies
from nld.parameters.execution_params_def import (
    ExecutionParameterDefinition,
)
from nld.service import EntityTypeNames
from nld.task.base import StandardTask
from nld.utils import format_exception_chain

from .data_flow_executor import DataFlowExecutor


class DataFlowExecutionTask(StandardTask):
    """Execute one or more data flows in dependency order.

    When a single flow ``name`` is provided, it is executed as a batch
    of one. When only a ``namespace`` is given, all flows in that
    namespace are discovered, ordered topologically, and executed
    sequentially. On failure, transitive dependents are skipped while
    independent flows continue.

    The ``--upstream`` and ``--downstream`` flags expand the execution
    scope to include flows in the lineage of the specified flow or
    namespace.

    When ``render=True``, each flow's SQL query is rendered from flow
    metadata before execution.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(
            name="name",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="namespace",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="render",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="downstream",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="upstream",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="with_views",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="planned_state_strategy",
            mandatory=False,
        ),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        name: str | None = None,
        namespace: str | None = None,
        render: bool = False,
        downstream: bool = False,
        upstream: bool = False,
        with_views: bool = False,
        planned_state_strategy: str = PlannedStateStrategy.AUTO,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the DataFlowExecutionTask.

        Args:
            name: Name of a single data flow to execute
            namespace: Namespace whose flows should all be executed
            render: When True, render SQL from flow metadata before executing
            downstream: Include downstream lineage flows
            upstream: Include upstream lineage flows
            with_views: When True, execute VIEW flows instead of skipping them
            planned_state_strategy: How to react to an available planned state
                (see ``PlannedStateStrategy``); defaults to AUTO.
            **kwargs: Additional arguments (e.g., exec_uuid)
        """
        super().__init__(**kwargs)
        self.flow_name = name
        self.flow_namespace = namespace
        self.render = render
        self.downstream = downstream
        self.upstream = upstream
        self.with_views = with_views
        self.planned_state_strategy = planned_state_strategy

        if name is None and namespace is None:
            raise ValueError("Either 'name' or 'namespace' must be provided.")

        if (downstream or upstream) and name is None and namespace is None:
            raise ValueError(
                "--downstream and --upstream require --name or --namespace."
            )

        self.execution_context.load_entities(
            entity_types=[EntityTypeNames.DATA_FLOW_DEFINITION]
        )

        if downstream or upstream:
            self.flow_dict = self._resolve_lineage_flows()
        elif name is not None:
            namespaced_flow = (
                self.execution_context.entity_registry.get_data_flow_definition(
                    entity_key=name,
                    namespace=namespace,
                )
            )
            self.flow_dict = {name: namespaced_flow}
        else:
            self.flow_dict = (
                self.execution_context.entity_registry.get_data_flow_definition_dict(
                    namespace=namespace,
                )
            )

        if not self.flow_dict:
            self.log_warn("No flows found for the given parameters")
            self.graph: DataFlowGraph | None = None
            self.execution_order: list[str] = []
            return

        self.graph = DataFlowGraph(flow_dict=self.flow_dict)
        self.execution_order = self.graph.topological_sort()

        self.log_info(f"Found {len(self.execution_order)} flow(s) to execute")
        display_order = [
            strip_node_type_prefix(node_id=fid) for fid in self.execution_order
        ]
        self.log_debug(f"Execution order: {', '.join(display_order)}")

    def _resolve_lineage_flows(
        self,
    ) -> dict[str, NamespacedDataFlowDefinition]:
        """Build the full graph and filter to lineage flows only."""
        all_flows = (
            self.execution_context.entity_registry.get_data_flow_definition_dict()
        )
        if not all_flows:
            return {}

        full_graph = DataFlowGraph(flow_dict=all_flows)

        include_downstream = self.downstream or not self.upstream
        include_upstream = self.upstream or not self.downstream

        scoped_graph = full_graph.get_scoped_subgraph(
            name=self.flow_name,
            namespace=self.flow_namespace,
            node_type=FLOW_NODE_TYPE,
            upstream=include_upstream,
            downstream=include_downstream,
        )

        return {
            strip_node_type_prefix(node_id=flow_id): scoped_graph.get_flow(
                flow_id=flow_id,
            )
            for flow_id in scoped_graph.flow_ids
        }

    def run(self, **kwargs: Any) -> FlowExecutionInfoWrapper:
        """Execute flows sequentially in topological order."""
        display_order = [
            strip_node_type_prefix(node_id=fid) for fid in self.execution_order
        ]
        batch_info = FlowExecutionInfoWrapper(
            namespace=self.flow_namespace or ".",
            execution_order=display_order,
        )

        skipped_flow_ids: dict[str, str] = {}
        total_flows = len(self.execution_order)

        for flow_index, flow_id in enumerate(self.execution_order, start=1):
            display_id = strip_node_type_prefix(node_id=flow_id)
            log_prefix = f"[{flow_index}/{total_flows}]"

            if flow_id in skipped_flow_ids:
                predecessor_display_id = skipped_flow_ids[flow_id]
                batch_info.skipped_flows[display_id] = predecessor_display_id
                self.log_warn(
                    f"{log_prefix} ⏭  Flow '{display_id}' skipped "
                    f"(predecessor '{predecessor_display_id}' failed)",
                )
                continue

            if (
                self.flow_name is None
                and not self.with_views
                and self._is_view_flow(flow_id=flow_id)
            ):
                batch_info.skipped_views.append(display_id)
                self.log_info(
                    f"{log_prefix} ⏭  Flow '{display_id}' skipped (view)",
                )
                continue

            namespaced_flow = self._get_flow(flow_id=flow_id)
            if namespaced_flow is None:
                error_msg = f"Flow '{display_id}' not found in registry"
                batch_info.failed_flows[display_id] = error_msg
                self.log_error(f"{log_prefix} {error_msg}")
                self._skip_dependents(
                    failed_flow_id=flow_id,
                    failed_display_id=display_id,
                    skipped_flow_ids=skipped_flow_ids,
                )
                continue

            target_name = (
                namespaced_flow.model.target_structure.entity_name
                if namespaced_flow.model.target_structure is not None
                else display_id
            )
            self.log_info(f"{log_prefix} Flow starting : {display_id}")
            self.log_info(f"{log_prefix} Target: {target_name}")

            try:
                flow_result = self._execute_single_flow(
                    namespaced_flow=namespaced_flow,
                    log_prefix=log_prefix,
                )
                if flow_result.execution_status == FlowExecStatus.FAILED:
                    error_msg = flow_result.execution_error or "flow reported failure"
                    batch_info.failed_flows[display_id] = error_msg
                    duration = _format_flow_duration(flow_result=flow_result)
                    self.log_error(
                        f"{log_prefix} ❌ Flow '{display_id}' failed "
                        f"in {duration}: {error_msg}",
                    )
                    self._skip_dependents(
                        failed_flow_id=flow_id,
                        failed_display_id=display_id,
                        skipped_flow_ids=skipped_flow_ids,
                    )
                else:
                    batch_info.flow_results.append(flow_result)
                    duration = _format_flow_duration(flow_result=flow_result)
                    self.log_info(
                        f"{log_prefix} ✅ Flow '{display_id}' completed in {duration}",
                    )
            except Exception as ex:
                error_msg = format_exception_chain(exception=ex)
                batch_info.failed_flows[display_id] = error_msg
                self.log_error(
                    f"{log_prefix} ❌ Flow '{display_id}' failed:\n{error_msg}",
                )
                self._skip_dependents(
                    failed_flow_id=flow_id,
                    failed_display_id=display_id,
                    skipped_flow_ids=skipped_flow_ids,
                )

        return batch_info

    def _get_flow(
        self,
        flow_id: str,
    ) -> NamespacedDataFlowDefinition | None:
        """Look up a NamespacedDataFlowDefinition by its graph node ID."""
        try:
            return self.graph.get_flow(flow_id=flow_id)  # type: ignore[union-attr]
        except KeyError:
            return None

    def _skip_dependents(
        self,
        failed_flow_id: str,
        failed_display_id: str,
        skipped_flow_ids: dict[str, str],
    ) -> None:
        """Mark transitive dependents for skipping."""
        if self.graph is not None:
            dependents = self.graph.get_transitive_dependents(
                flow_id=failed_flow_id,
            )
            for dependent_id in dependents:
                if dependent_id not in skipped_flow_ids:
                    skipped_flow_ids[dependent_id] = failed_display_id

    def _is_view_flow(self, flow_id: str) -> bool:
        """Check whether a flow uses the VIEW write strategy."""
        namespaced_flow = self._get_flow(flow_id=flow_id)
        if namespaced_flow is None:
            return False
        return namespaced_flow.model.write_strategy == FlowUpdateStrategies.VIEW

    def _execute_single_flow(
        self,
        namespaced_flow: NamespacedDataFlowDefinition,
        log_prefix: str = "",
    ) -> FlowExecutionInfo:
        """Initialize and execute a single data flow."""
        if self.render:
            self._render_sql_for_flow(namespaced_flow=namespaced_flow)

        executor = DataFlowExecutor(
            namespaced_data_flow_definition=namespaced_flow,
            params=self.execution_context.task_request.get_parameters(),
            planned_state_strategy=self.planned_state_strategy,
        )
        data_flow_task = executor.init_data_flow_task(
            connections_should_be_opened=True,
        )
        data_flow_task.log_prefix = log_prefix
        return executor.execute_data_flow_task(data_flow_task=data_flow_task)

    def _render_sql_for_flow(
        self,
        namespaced_flow: NamespacedDataFlowDefinition,
    ) -> None:
        """Render SQL from flow metadata before execution."""
        entities_root = self.execution_context.project.entities_root_folder_path
        rendering_executor = SQLRenderingExecutor(
            namespaced_data_flow_definition=namespaced_flow,
            override_output_folder_path=entities_root,
        )
        rendering_task = rendering_executor.init_task()
        rendering_executor.execute(task=rendering_task)


def _format_flow_duration(flow_result: FlowExecutionInfo) -> str:
    """Render a flow duration for user-facing log lines.

    Computes the elapsed seconds from `started_at`/`ended_at` because
    `FlowExecutionInfo` does not carry a pre-aggregated duration field.
    Missing timestamps surface as an em-dash so readers see "not
    available" rather than mistaking a zero for a real measurement.
    """
    if flow_result.started_at is None or flow_result.ended_at is None:
        return "—"
    seconds = (flow_result.ended_at - flow_result.started_at).total_seconds()
    return f"{seconds:.3f}s"
