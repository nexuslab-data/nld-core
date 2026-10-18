from typing import TYPE_CHECKING

from nld.flow.definition import DataFlowDefinition, NamespacedDataFlowDefinition
from nld.pydantic import NldEntityReference, NldNamespace
from nld.scheduling.models import (
    FlowTask,
    FlowTrigger,
    NamespacedFlowTaskModel,
    ScheduleTrigger,
)
from nld.scheduling.scheduling_exceptions import (
    NldSchedulingPredecessorError,
    NldSchedulingReferenceError,
)
from nld.scheduling.services.graph import SchedulingGraph

if TYPE_CHECKING:
    from nld.service import NldEntityRegistry


class SchedulingResolver:
    """Resolves the active scheduling graph for a single environment.

    Nodes are FlowTask entities active in the requested environment.
    Flow-trigger preconditions reference upstream tasks, so a task's trigger
    can depend on another task. When a flow trigger has no explicit
    preconditions, upstream tasks are derived from the flow dependency graph
    (a task is upstream when the flow it schedules produces a structure that
    is a predecessor of this task's flow).

    Tasks may share a name across namespaces, like the flows they schedule.
    A bare ``flow`` or predecessor reference (``load_customer``) is therefore
    looked up in the declaring task's own namespace first, then project-wide.
    """

    def __init__(self, environment: str, registry: "NldEntityRegistry") -> None:
        self._environment = environment
        self._registry = registry
        self._flow_by_id: dict[str, NamespacedDataFlowDefinition] = {}
        self._structure_to_flow_id: dict[str, str] = {}
        self._task_by_id: dict[str, NamespacedFlowTaskModel] = {}

    def resolve(self) -> SchedulingGraph:
        """Build the environment's SchedulingGraph."""
        self._build_flow_indexes()
        flow_tasks = self._registry.get_flow_task_dict().values()
        self._task_by_id = {task.id: task for task in flow_tasks}

        graph = SchedulingGraph()
        # node_id -> (namespaced task, scheduled flow id)
        active_nodes: dict[str, tuple[NamespacedFlowTaskModel, str]] = {}
        # scheduled flow id -> task node id (for derivation)
        flow_id_to_node: dict[str, str] = {}

        for task in flow_tasks:
            model = task.model
            if not model.is_active_in(self._environment):
                continue
            env_scheduling = model.for_environment(self._environment)
            if env_scheduling is None or env_scheduling.trigger is None:
                continue
            flow_id = self._resolve_flow_reference(
                model.flow,
                task_id=task.id,
                task_namespace=task.namespace,
            ).id
            trigger = env_scheduling.trigger
            cron = trigger.cron if isinstance(trigger, ScheduleTrigger) else None
            graph.add_task(
                node_id=task.id,
                namespace=str(task.namespace),
                task_name=model.name,
                trigger_kind=trigger.kind,
                cron=cron,
                params=model.merged_params(self._environment),
                frequency=model.resolved_frequency(self._environment),
            )
            active_nodes[task.id] = (task, flow_id)
            flow_id_to_node[flow_id] = task.id

        self._add_trigger_edges(
            graph=graph,
            active_nodes=active_nodes,
            flow_id_to_node=flow_id_to_node,
        )
        return graph

    def _add_trigger_edges(
        self,
        graph: SchedulingGraph,
        active_nodes: dict[str, tuple[NamespacedFlowTaskModel, str]],
        flow_id_to_node: dict[str, str],
    ) -> None:
        """Add precondition edges between active tasks.

        External predecessors live in another data product: they are not
        resolved against the local registry, but are surfaced as external
        source nodes with a dotted edge so the dependency stays visible.
        """
        for node_id, (task, flow_id) in active_nodes.items():
            env_scheduling = task.model.for_environment(self._environment)
            trigger = env_scheduling.trigger if env_scheduling else None
            if not isinstance(trigger, FlowTrigger):
                continue
            self._add_adjusted_lineage_edges(
                graph=graph,
                active_nodes=active_nodes,
                flow_id_to_node=flow_id_to_node,
                node_id=node_id,
                flow_id=flow_id,
                trigger=trigger,
                task_namespace=task.namespace,
            )

    def _add_adjusted_lineage_edges(
        self,
        graph: SchedulingGraph,
        active_nodes: dict[str, tuple[NamespacedFlowTaskModel, str]],
        flow_id_to_node: dict[str, str],
        node_id: str,
        flow_id: str,
        trigger: FlowTrigger,
        task_namespace: NldNamespace,
    ) -> None:
        """Add edges from explicit predecessors, or from the automatic lineage.

        A non-empty ``predecessors`` list is a full override: the automatic
        lineage is never derived, and the upstream set is exactly
        ``get_all_predecessors()`` (``predecessors`` + ``additional_predecessors``,
        net of ``excluded_predecessors``). Otherwise the final upstream set is
        derived lineage | get_all_predecessors() (i.e. ``additional_predecessors``,
        net of ``excluded_predecessors``), and a local addition already present
        in the derived lineage is a configuration error.
        """
        is_override = bool(trigger.predecessors)
        derived_ids: set[str] = set()
        if not is_override:
            derived_ids = set(
                self._derive_upstream_node_ids(
                    flow_id=flow_id,
                    flow_id_to_node=flow_id_to_node,
                )
            )

        addition_ids: set[str] = set()
        for addition in trigger.get_all_predecessors():
            if addition.external:
                self._add_external_edge(
                    graph=graph,
                    reference=addition.name,
                    nld_project=addition.nld_project,
                    downstream_node_id=node_id,
                )
                continue
            addition_id = self._resolve_task_reference(
                addition.name,
                task_id=node_id,
                task_namespace=task_namespace,
            ).id
            if not is_override and addition_id in derived_ids:
                raise NldSchedulingPredecessorError(
                    f"Task '{node_id}' declares '{addition_id}' in "
                    "additional_predecessors, but it is already part of the "
                    "automatically derived lineage."
                )
            addition_ids.add(addition_id)

        upstream_ids = addition_ids if is_override else derived_ids | addition_ids
        for upstream_id in upstream_ids:
            if upstream_id in active_nodes and upstream_id != node_id:
                graph.add_edge(
                    upstream_node_id=upstream_id,
                    downstream_node_id=node_id,
                )

    @staticmethod
    def _add_external_edge(
        graph: SchedulingGraph,
        reference: NldEntityReference[FlowTask],
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
            task_name=entity_name,
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
        """Derive upstream task node ids from the flow's predecessors."""
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

    @staticmethod
    def _build_task_local_id(
        reference: str,
        task_namespace: NldNamespace,
    ) -> str | None:
        """Return the id a bare reference designates in its task's namespace.

        Only a bare reference is read relative to the declaring task, since
        a qualified (``sales.load_customer``) or root-anchored reference
        (``.load_customer``) names its namespace already. A root task needs
        no local id, as the project-wide lookup starts at the root.

        Example:
            >>> SchedulingResolver._build_task_local_id(
            ...     "load_customer",
            ...     task_namespace=NldNamespace("sales"),
            ... )
            'sales.load_customer'
        """
        if "." in reference or task_namespace.is_root:
            return None
        return f"{task_namespace}.{reference}"

    def _resolve_flow_reference(
        self,
        reference: NldEntityReference[DataFlowDefinition],
        task_id: str,
        task_namespace: NldNamespace,
    ) -> NamespacedDataFlowDefinition:
        """Resolve a task's flow reference, the task's namespace first.

        Without this, a bare ``flow: load_customer`` declared in ``sales``
        would bind to a root ``load_customer`` flow, or be rejected as
        ambiguous, although ``sales`` holds a flow of that name.
        """
        local_id = self._build_task_local_id(
            reference,
            task_namespace=task_namespace,
        )
        if local_id is not None and local_id in self._flow_by_id:
            return self._flow_by_id[local_id]
        try:
            return self._registry.get_data_flow_definition(
                entity_key=reference.entity_name,
                namespace=str(reference.namespace),
            )
        except (ValueError, RuntimeError) as error:
            raise NldSchedulingReferenceError(
                f"Task '{task_id}' cannot resolve its flow '{reference}': {error}"
            ) from error

    def _resolve_task_reference(
        self,
        reference: NldEntityReference[FlowTask],
        task_id: str,
        task_namespace: NldNamespace,
    ) -> NamespacedFlowTaskModel:
        """Resolve a predecessor task reference, the task's namespace first."""
        local_id = self._build_task_local_id(
            reference,
            task_namespace=task_namespace,
        )
        if local_id is not None and local_id in self._task_by_id:
            return self._task_by_id[local_id]
        try:
            return self._registry.get_flow_task(
                entity_key=reference.entity_name,
                namespace=str(reference.namespace),
            )
        except (ValueError, RuntimeError) as error:
            raise NldSchedulingReferenceError(
                f"Task '{task_id}' cannot resolve its predecessor "
                f"'{reference}': {error}"
            ) from error
