from typing import TYPE_CHECKING

from nld.flow.definition import DataFlowDefinition, NamespacedDataFlowDefinition
from nld.pydantic import NldEntityReference
from nld.scheduling.models import (
    FlowScheduling,
    FlowTrigger,
    NamespacedFlowSchedulingModel,
    ScheduleTrigger,
)
from nld.scheduling.scheduling_exceptions import NldSchedulingReferenceError
from nld.scheduling.services.graph import SchedulingGraph

if TYPE_CHECKING:
    from nld.service import NldEntityRegistry


class SchedulingResolver:
    """Resolves the active scheduling graph for a single environment.

    Nodes are scheduling entities (scheduled tasks) active in the requested
    environment. Flow-trigger preconditions reference upstream schedulings, so
    scheduling depends on scheduling. When a flow trigger has no explicit
    preconditions, upstream schedulings are derived from the flow dependency
    graph (a scheduling is upstream when the flow it schedules produces a
    structure that is a predecessor of this scheduling's flow).
    """

    def __init__(self, environment: str, registry: "NldEntityRegistry") -> None:
        self._environment = environment
        self._registry = registry
        self._flow_by_id: dict[str, NamespacedDataFlowDefinition] = {}
        self._structure_to_flow_id: dict[str, str] = {}

    def resolve(self) -> SchedulingGraph:
        """Build the environment's SchedulingGraph."""
        self._build_flow_indexes()

        graph = SchedulingGraph()
        # node_id -> (scheduling model, scheduled flow id)
        active_nodes: dict[str, tuple[FlowScheduling, str]] = {}
        # scheduled flow id -> scheduling node id (for derivation)
        flow_id_to_node: dict[str, str] = {}

        for scheduling in self._registry.get_flow_scheduling_dict().values():
            model = scheduling.model
            if not model.is_active_in(self._environment):
                continue
            env_scheduling = model.for_environment(self._environment)
            if env_scheduling is None or env_scheduling.trigger is None:
                continue
            flow_id = self._resolve_flow_reference(model.flow).id
            trigger = env_scheduling.trigger
            cron = trigger.cron if isinstance(trigger, ScheduleTrigger) else None
            graph.add_flow(
                node_id=scheduling.id,
                namespace=str(scheduling.namespace),
                flow_name=model.name,
                trigger_kind=trigger.kind,
                cron=cron,
                params=model.merged_params(self._environment),
            )
            active_nodes[scheduling.id] = (model, flow_id)
            flow_id_to_node[flow_id] = scheduling.id

        self._add_trigger_edges(
            graph=graph,
            active_nodes=active_nodes,
            flow_id_to_node=flow_id_to_node,
        )
        return graph

    def _add_trigger_edges(
        self,
        graph: SchedulingGraph,
        active_nodes: dict[str, tuple[FlowScheduling, str]],
        flow_id_to_node: dict[str, str],
    ) -> None:
        """Add precondition edges between active schedulings.

        External predecessors live in another data product: they are not
        resolved against the local registry, but are surfaced as external
        source nodes with a dotted edge so the dependency stays visible.
        """
        for node_id, (model, flow_id) in active_nodes.items():
            env_scheduling = model.for_environment(self._environment)
            trigger = env_scheduling.trigger if env_scheduling else None
            if not isinstance(trigger, FlowTrigger):
                continue
            if trigger.predecessors:
                for predecessor in trigger.predecessors:
                    if predecessor.external:
                        self._add_external_edge(
                            graph=graph,
                            reference=predecessor.name,
                            nld_project=predecessor.nld_project,
                            downstream_node_id=node_id,
                        )
                        continue
                    upstream_id = self._resolve_scheduling_reference(
                        predecessor.name,
                    ).id
                    if upstream_id in active_nodes and upstream_id != node_id:
                        graph.add_edge(
                            upstream_node_id=upstream_id,
                            downstream_node_id=node_id,
                        )
            else:
                upstream_ids = self._derive_upstream_node_ids(
                    flow_id=flow_id,
                    flow_id_to_node=flow_id_to_node,
                )
                for upstream_id in upstream_ids:
                    if upstream_id in active_nodes and upstream_id != node_id:
                        graph.add_edge(
                            upstream_node_id=upstream_id,
                            downstream_node_id=node_id,
                        )

    @staticmethod
    def _add_external_edge(
        graph: SchedulingGraph,
        reference: NldEntityReference[FlowScheduling],
        nld_project: str | None,
        downstream_node_id: str,
    ) -> None:
        """Add an external source node and a dotted edge into a local node.

        When ``nld_project`` is set the external predecessor's ``name`` is the
        bare entity name; the source node is qualified by the upstream project.
        Otherwise the (legacy) fully-qualified reference is used as-is.
        """
        entity_name = reference.entity_name
        if nld_project is not None:
            external_id = f"{nld_project}.{entity_name}"
            namespace = nld_project
        else:
            external_id = str(reference)
            namespace = str(reference.namespace)
        graph.add_external_source(
            node_id=external_id,
            namespace=namespace,
            flow_name=entity_name,
        )
        graph.add_edge(
            upstream_node_id=external_id,
            downstream_node_id=downstream_node_id,
            external=True,
        )

    def _derive_upstream_node_ids(
        self,
        flow_id: str,
        flow_id_to_node: dict[str, str],
    ) -> list[str]:
        """Derive upstream scheduling node ids from the flow's predecessors."""
        namespaced_flow = self._flow_by_id.get(flow_id)
        if namespaced_flow is None:
            return []
        upstream_ids: list[str] = []
        for predecessor in namespaced_flow.model.predecessors.values():
            structure_id = str(predecessor.full_path)
            producing_flow_id = self._structure_to_flow_id.get(structure_id)
            if producing_flow_id is None:
                continue
            upstream_node_id = flow_id_to_node.get(producing_flow_id)
            if upstream_node_id is not None:
                upstream_ids.append(upstream_node_id)
        return upstream_ids

    def _build_flow_indexes(self) -> None:
        """Index flows by id and by produced target structure."""
        flow_dict = self._registry.get_data_flow_definition_dict()
        for namespaced_flow in flow_dict.values():
            self._flow_by_id[namespaced_flow.id] = namespaced_flow
            target_structure = namespaced_flow.model.target_structure
            if target_structure is not None:
                self._structure_to_flow_id[str(target_structure)] = namespaced_flow.id

    def _resolve_flow_reference(
        self,
        reference: NldEntityReference[DataFlowDefinition],
    ) -> NamespacedDataFlowDefinition:
        """Resolve a flow entity reference to its NamespacedDataFlowDefinition."""
        try:
            return self._registry.get_data_flow_definition(
                entity_key=reference.entity_name,
                namespace=str(reference.namespace),
            )
        except (ValueError, RuntimeError) as error:
            raise NldSchedulingReferenceError(
                f"Scheduling references unknown flow '{reference}': {error}"
            ) from error

    def _resolve_scheduling_reference(
        self,
        reference: NldEntityReference[FlowScheduling],
    ) -> NamespacedFlowSchedulingModel:
        """Resolve a scheduling entity reference to its namespaced wrapper."""
        try:
            return self._registry.get_flow_scheduling(
                entity_key=reference.entity_name,
                namespace=str(reference.namespace),
            )
        except (ValueError, RuntimeError) as error:
            raise NldSchedulingReferenceError(
                f"Precondition references unknown scheduling '{reference}': {error}"
            ) from error
