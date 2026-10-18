import networkx as nx

from nld.docs.models import (
    NODE_TYPE_FLOW,
    NODE_TYPE_STRUCTURE,
    DocsLineage,
    DocsLineageEdge,
    DocsLineageNode,
)
from nld.flow.graph import (
    FLOW_NODE_TYPE,
    STRUCTURE_NODE_TYPE,
    DataFlowGraph,
    build_node_id,
    strip_node_type_prefix,
)


def _node_label(entity_id: str) -> str:
    """Return the last segment of an entity id, used as the node label."""
    _, separator, name = entity_id.rpartition(".")
    return name if separator else entity_id


def _node_namespace(entity_id: str) -> str | None:
    """Return the namespace part of an entity id, None at the root."""
    namespace, separator, _ = entity_id.rpartition(".")
    return namespace if separator else None


def _compute_layers(digraph: nx.DiGraph) -> dict[str, int]:
    """Assign every node the length of the longest path reaching it.

    A longest-path rank is what makes the drawing read left to right: a node
    always sits to the right of every node it depends on, which a simple
    breadth-first rank does not guarantee on a diamond-shaped graph.
    """
    layers: dict[str, int] = {}
    try:
        ordered = list(nx.topological_sort(digraph))  # type: ignore[func-returns-value]
    except nx.NetworkXUnfeasible:
        # A cycle means the project is not deployable, but the picture is
        # still worth drawing, so fall back to a flat layout.
        return dict.fromkeys(digraph.nodes, 0)

    for node_id in ordered:
        predecessor_layers = [
            layers.get(predecessor, 0) + 1
            for predecessor in digraph.predecessors(node_id)  # type: ignore[no-untyped-call]
        ]
        layers[node_id] = max(predecessor_layers, default=0)
    return layers


def build_lineage_key(
    node_type: str,
    entity_id: str,
) -> str:
    """Build the typed key the UI addresses a lineage node by."""
    return f"{node_type}:{entity_id}"


def _docs_node_type(node_type: str | None) -> str:
    """Map a flow-graph node type onto the two kinds the UI draws."""
    return NODE_TYPE_FLOW if node_type == FLOW_NODE_TYPE else NODE_TYPE_STRUCTURE


def _docs_key(
    graph: DataFlowGraph,
    node_id: str,
) -> str:
    """Return the typed key of a flow-graph node."""
    return build_lineage_key(
        node_type=_docs_node_type(node_type=graph.get_node_type(node_id=node_id)),
        entity_id=strip_node_type_prefix(node_id=node_id),
    )


def build_lineage(
    graph: DataFlowGraph,
    existing_keys: set[str] | None = None,
    external_owners: dict[str, str] | None = None,
) -> DocsLineage:
    """Turn the flow dependency graph into the payload the UI draws.

    The graph keeps every reference a flow makes, declared or not; when
    ``existing_keys`` is given, a node whose key is not in it is flagged
    ``missing`` so the drawing shows the dangling reference for what it is.
    """
    digraph = graph.digraph
    layers = _compute_layers(digraph=digraph)

    nodes: list[DocsLineageNode] = []
    for node_id in sorted(digraph.nodes):
        node_type = _docs_node_type(node_type=graph.get_node_type(node_id=node_id))
        entity_id = strip_node_type_prefix(node_id=node_id)
        key = build_lineage_key(
            node_type=node_type,
            entity_id=entity_id,
        )
        nodes.append(
            DocsLineageNode(
                key=key,
                node_id=entity_id,
                node_type=node_type,
                label=_node_label(entity_id=entity_id),
                namespace=_node_namespace(entity_id=entity_id),
                layer=layers.get(node_id, 0),
                missing=(
                    existing_keys is not None
                    and key not in existing_keys
                    and not (external_owners or {}).get(entity_id)
                ),
                external=bool((external_owners or {}).get(entity_id)),
                external_project=(external_owners or {}).get(entity_id),
            )
        )

    edges = [
        DocsLineageEdge(
            source=_docs_key(graph=graph, node_id=source),
            target=_docs_key(graph=graph, node_id=target),
        )
        for source, target in sorted(digraph.edges)
    ]

    return DocsLineage(
        nodes=nodes,
        edges=edges,
    )


def collect_structure_neighbours(
    graph: DataFlowGraph,
    structure_id: str,
) -> tuple[list[str], list[str]]:
    """Return the flows producing and the flows consuming one structure."""
    node_id = build_node_id(
        node_type=STRUCTURE_NODE_TYPE,
        entity_id=structure_id,
    )
    digraph = graph.digraph
    if node_id not in digraph:
        return [], []

    predecessors: list[str] = list(digraph.predecessors(node_id))  # type: ignore[no-untyped-call]
    successors: list[str] = list(digraph.successors(node_id))  # type: ignore[no-untyped-call]
    produced_by = sorted(
        strip_node_type_prefix(node_id=predecessor)
        for predecessor in predecessors
        if graph.get_node_type(node_id=predecessor) == FLOW_NODE_TYPE
    )
    consumed_by = sorted(
        strip_node_type_prefix(node_id=successor)
        for successor in successors
        if graph.get_node_type(node_id=successor) == FLOW_NODE_TYPE
    )
    return produced_by, consumed_by
