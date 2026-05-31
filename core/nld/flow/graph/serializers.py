from typing import Any

from nld.flow.graph.data_flow_graph import (
    FLOW_NODE_TYPE,
    STRUCTURE_NODE_TYPE,
    DataFlowGraph,
    strip_node_type_prefix,
)

MERMAID_NODE_ID_REPLACEMENTS = {
    ".": "_",
    "-": "_",
    " ": "_",
}

MERMAID_FLOW_NODE_COLOR = "#4A90D9"
MERMAID_STRUCTURE_NODE_COLOR = "#7CB342"


def serialize_mermaid_graph(
    graph: DataFlowGraph,
) -> str:
    """Serialize graph to a Mermaid flowchart diagram string."""
    lines: list[str] = [
        "graph LR",
        f"    classDef flowNode fill:{MERMAID_FLOW_NODE_COLOR},color:#fff",
        f"    classDef structureNode fill:{MERMAID_STRUCTURE_NODE_COLOR},color:#fff",
        "",
    ]

    nodes = serialize_simplified_nodes(graph=graph)
    for node in nodes:
        mermaid_id = _to_mermaid_node_id(node_id=node["id"])
        label = _build_mermaid_node_label(node_id=node["id"])
        node_type = node["type"]
        class_suffix = "flowNode" if node_type == FLOW_NODE_TYPE else "structureNode"
        lines.append(f'    {mermaid_id}["{label}"]:::{class_suffix}')

    lines.append("")

    edges = serialize_simplified_edges(graph=graph)
    for edge in edges:
        source = _to_mermaid_node_id(node_id=edge["source"])
        target = _to_mermaid_node_id(node_id=edge["target"])
        lines.append(f"    {source} --> {target}")

    lines.append("")
    return "\n".join(lines)


def _to_mermaid_node_id(
    node_id: str,
) -> str:
    """Convert a node ID to a valid Mermaid node identifier."""
    result = node_id
    for old_char, new_char in MERMAID_NODE_ID_REPLACEMENTS.items():
        result = result.replace(old_char, new_char)
    return result


def _build_mermaid_node_label(
    node_id: str,
) -> str:
    """Build a two-line Mermaid label from a node ID.

    Strips the type prefix and splits namespace from entity
    name onto separate lines using a Mermaid line break.
    """
    entity_id = strip_node_type_prefix(node_id=node_id)
    parts = entity_id.split(".", maxsplit=1)
    if len(parts) == 2:
        return f"{parts[0]}<br/>{parts[1]}"
    return entity_id


def serialize_simplified_nodes(
    graph: DataFlowGraph,
) -> list[dict[str, Any]]:
    """Serialize graph nodes to a sorted list of simplified dicts."""
    nodes: list[dict[str, Any]] = []

    for flow_id in graph.flow_ids:
        namespaced_flow = graph.get_flow(flow_id=flow_id)
        flow_definition = namespaced_flow.model

        node: dict[str, Any] = {
            "id": flow_id,
            "type": FLOW_NODE_TYPE,
            "namespace": str(namespaced_flow.namespace),
            "name": flow_definition.name,
        }

        if flow_definition.target_structure is not None:
            node["target_structure"] = str(flow_definition.target_structure)

        nodes.append(node)

    for structure_id in graph.structure_ids:
        nodes.append(
            {
                "id": structure_id,
                "type": STRUCTURE_NODE_TYPE,
            }
        )

    return nodes


def serialize_simplified_edges(
    graph: DataFlowGraph,
) -> list[dict[str, str]]:
    """Serialize graph edges to a sorted list of simplified dicts."""
    edges: list[dict[str, str]] = []
    for source, target in graph.digraph.edges():
        edges.append(
            {
                "source": source,
                "target": target,
            }
        )

    return sorted(
        edges,
        key=lambda edge: (edge["source"], edge["target"]),
    )
