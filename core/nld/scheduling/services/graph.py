from typing import Any

import networkx as nx

TRIGGER_KIND_ATTRIBUTE = "trigger_kind"
CRON_ATTRIBUTE = "cron"
NAMESPACE_ATTRIBUTE = "namespace"
FLOW_NAME_ATTRIBUTE = "flow_name"
PARAMS_ATTRIBUTE = "params"
EXTERNAL_ATTRIBUTE = "external"

EXTERNAL_TRIGGER_KIND = "external"


def build_scheduling_node_id(namespace: str, flow_name: str) -> str:
    """Build a scheduling node id from a namespace and a flow name."""
    if not namespace or namespace == ".":
        return flow_name
    return f"{namespace}.{flow_name}"


class SchedulingGraph:
    """Directed graph of an environment's scheduled flows.

    Nodes are flows active in a single environment. Each node carries its
    trigger kind (``schedule`` or ``flow``) and, for schedule triggers, its
    cron. Edges link an upstream flow to a downstream flow that is triggered by
    it (``upstream -> downstream``).
    """

    def __init__(self) -> None:
        self._digraph = nx.DiGraph()

    def add_flow(
        self,
        node_id: str,
        namespace: str,
        flow_name: str,
        trigger_kind: str,
        cron: str | None = None,
        params: dict[str, Any] | None = None,
        external: bool = False,
    ) -> str:
        """Add a scheduled flow node and return its id.

        ``external`` marks a node that lives in another data product (an
        upstream source referenced by a cross-product predecessor).
        """
        self._digraph.add_node(
            node_id,
            **{
                NAMESPACE_ATTRIBUTE: namespace,
                FLOW_NAME_ATTRIBUTE: flow_name,
                TRIGGER_KIND_ATTRIBUTE: trigger_kind,
                CRON_ATTRIBUTE: cron,
                PARAMS_ATTRIBUTE: params or {},
                EXTERNAL_ATTRIBUTE: external,
            },
        )
        return node_id

    def add_external_source(self, node_id: str, namespace: str, flow_name: str) -> str:
        """Add (idempotently) an external upstream source node."""
        return self.add_flow(
            node_id=node_id,
            namespace=namespace,
            flow_name=flow_name,
            trigger_kind=EXTERNAL_TRIGGER_KIND,
            external=True,
        )

    def add_edge(
        self,
        upstream_node_id: str,
        downstream_node_id: str,
        external: bool = False,
    ) -> None:
        """Add a trigger edge from an upstream flow to a downstream flow.

        ``external`` marks an edge whose upstream is in another data product.
        """
        self._digraph.add_edge(
            upstream_node_id,
            downstream_node_id,
            **{EXTERNAL_ATTRIBUTE: external},
        )

    @property
    def node_ids(self) -> list[str]:
        """Return all node ids."""
        return list(self._digraph.nodes)

    def has_node(self, node_id: str) -> bool:
        """Whether a node id exists in the graph."""
        return node_id in self._digraph

    def has_flow(self, namespace: str, flow_name: str) -> bool:
        """Whether a flow is part of this environment's scheduling graph."""
        node_id = build_scheduling_node_id(
            namespace=namespace,
            flow_name=flow_name,
        )
        return node_id in self._digraph

    def find_node_ids_by_flow_name(self, flow_name: str) -> list[str]:
        """Return the ids of local (non-external) nodes with this flow name.

        Lets callers filter by ``--flow-name`` without knowing the namespace.
        """
        return sorted(
            node_id
            for node_id in self._digraph.nodes
            if self._digraph.nodes[node_id][FLOW_NAME_ATTRIBUTE] == flow_name
            and not self._digraph.nodes[node_id][EXTERNAL_ATTRIBUTE]
        )

    def is_schedule_root(self, namespace: str, flow_name: str) -> bool:
        """Whether a flow is present and schedule-triggered (a DAG root)."""
        node_id = build_scheduling_node_id(
            namespace=namespace,
            flow_name=flow_name,
        )
        if node_id not in self._digraph:
            return False
        return bool(self._digraph.nodes[node_id][TRIGGER_KIND_ATTRIBUTE] == "schedule")

    def find_cycle(self) -> list[str] | None:
        """Return the node ids forming a cycle, or None when the graph is acyclic."""
        try:
            cycle_edges = nx.find_cycle(self._digraph, orientation="original")
        except nx.NetworkXNoCycle:
            return None
        cycle_nodes = [edge[0] for edge in cycle_edges]
        cycle_nodes.append(cycle_edges[0][0])
        return cycle_nodes

    def get_lineage_subgraph(
        self,
        node_id: str,
        upstream: bool = True,
        downstream: bool = True,
    ) -> "SchedulingGraph":
        """Return a subgraph with the lineage of a node."""
        if node_id not in self._digraph:
            raise KeyError(f"Node '{node_id}' not found in the scheduling graph")
        lineage_nodes: set[str] = {node_id}
        if upstream:
            lineage_nodes |= nx.ancestors(self._digraph, source=node_id)  # type: ignore[no-untyped-call]
        if downstream:
            lineage_nodes |= nx.descendants(self._digraph, source=node_id)  # type: ignore[no-untyped-call]
        subgraph = SchedulingGraph()
        subgraph._digraph = self._digraph.subgraph(lineage_nodes).copy()  # type: ignore[no-untyped-call]
        return subgraph

    def serialize_nodes(self) -> list[dict[str, Any]]:
        """Serialize nodes to a sorted list of dicts."""
        nodes = []
        for node_id in sorted(self._digraph.nodes):
            data = self._digraph.nodes[node_id]
            nodes.append(
                {
                    "id": node_id,
                    "namespace": data[NAMESPACE_ATTRIBUTE],
                    "flow_name": data[FLOW_NAME_ATTRIBUTE],
                    "trigger_kind": data[TRIGGER_KIND_ATTRIBUTE],
                    "cron": data[CRON_ATTRIBUTE],
                    "params": data[PARAMS_ATTRIBUTE],
                    "external": data[EXTERNAL_ATTRIBUTE],
                }
            )
        return nodes

    def serialize_edges(self) -> list[dict[str, Any]]:
        """Serialize edges to a sorted list of dicts."""
        edges = [
            {
                "source": source,
                "target": target,
                "external": data.get(EXTERNAL_ATTRIBUTE, False),
            }
            for source, target, data in self._digraph.edges(data=True)
        ]
        return sorted(edges, key=lambda edge: (edge["source"], edge["target"]))

    def serialize_mermaid(self) -> str:
        """Serialize the graph to a Mermaid flowchart string.

        External source nodes are coloured via the ``external`` class and the
        edges that link them use a dotted style (``-.->``) to distinguish a
        cross-product dependency from an in-product one.
        """
        lines = ["flowchart TD"]
        lines.append(
            "    classDef external fill:#ffe0b2,stroke:#e65100,stroke-dasharray:4 3;"
        )
        external_ids: list[str] = []
        for node_id in sorted(self._digraph.nodes):
            data = self._digraph.nodes[node_id]
            kind = data[TRIGGER_KIND_ATTRIBUTE]
            cron = data[CRON_ATTRIBUTE]
            label = f"{node_id}<br/>{kind}"
            if cron:
                label = f"{label}<br/>{cron}"
            mermaid_id = self._mermaid_id(node_id)
            lines.append(f'    {mermaid_id}["{label}"]')
            if data[EXTERNAL_ATTRIBUTE]:
                external_ids.append(mermaid_id)
        for source, target, data in sorted(
            self._digraph.edges(data=True),
            key=lambda edge: (edge[0], edge[1]),
        ):
            arrow = "-.->" if data.get(EXTERNAL_ATTRIBUTE, False) else "-->"
            lines.append(
                f"    {self._mermaid_id(source)} {arrow} {self._mermaid_id(target)}"
            )
        for mermaid_id in external_ids:
            lines.append(f"    class {mermaid_id} external;")
        return "\n".join(lines)

    @staticmethod
    def _mermaid_id(node_id: str) -> str:
        """Build a Mermaid-safe node identifier."""
        return node_id.replace(".", "_").replace("-", "_")
