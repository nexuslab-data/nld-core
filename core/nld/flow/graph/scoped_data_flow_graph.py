from __future__ import annotations

from nld.flow.graph.data_flow_graph import (
    FLOW_NODE_TYPE,
    STRUCTURE_NODE_TYPE,
    DataFlowGraph,
)

IN_SCOPE_ATTRIBUTE: str = "in_scope"


class ScopedDataFlowGraph(DataFlowGraph):
    """A DataFlowGraph that marks nodes as in or out of deployment scope.

    Flow nodes are in scope if their ID is in the provided
    scoped_flow_ids set. Structure nodes are in scope if any
    in-scope flow has an edge TO them (target_structure only,
    not predecessors).
    """

    def __init__(
        self,
        source_graph: DataFlowGraph,
        scoped_flow_ids: set[str],
    ) -> None:
        instance = DataFlowGraph._from_digraph(
            digraph=source_graph.digraph.copy(),
        )
        self._digraph = instance._digraph
        self._mark_scope(scoped_flow_ids=scoped_flow_ids)

    def _mark_scope(
        self,
        scoped_flow_ids: set[str],
    ) -> None:
        """Mark flow and structure nodes with in_scope attribute."""
        in_scope_structure_ids: set[str] = set()

        for node_id, data in self._digraph.nodes(data=True):
            node_type = data.get(self.NODE_TYPE_ATTRIBUTE)

            if node_type == FLOW_NODE_TYPE:
                is_in_scope = node_id in scoped_flow_ids
                self._digraph.nodes[node_id][IN_SCOPE_ATTRIBUTE] = is_in_scope

                if is_in_scope:
                    for successor in self._digraph.successors(node_id):  # type: ignore[no-untyped-call]
                        successor_type = self._digraph.nodes[successor].get(
                            self.NODE_TYPE_ATTRIBUTE,
                        )
                        if successor_type == STRUCTURE_NODE_TYPE:
                            in_scope_structure_ids.add(successor)

        for node_id, data in self._digraph.nodes(data=True):
            if data.get(self.NODE_TYPE_ATTRIBUTE) == STRUCTURE_NODE_TYPE:
                self._digraph.nodes[node_id][IN_SCOPE_ATTRIBUTE] = (
                    node_id in in_scope_structure_ids
                )

    @property
    def scoped_flow_ids(self) -> list[str]:
        """Return sorted flow IDs that are in deployment scope."""
        return sorted(
            node_id
            for node_id, data in self._digraph.nodes(data=True)
            if data.get(self.NODE_TYPE_ATTRIBUTE) == FLOW_NODE_TYPE
            and data.get(IN_SCOPE_ATTRIBUTE) is True
        )

    @property
    def scoped_structure_ids(self) -> list[str]:
        """Return sorted structure IDs that are in deployment scope."""
        return sorted(
            node_id
            for node_id, data in self._digraph.nodes(data=True)
            if data.get(self.NODE_TYPE_ATTRIBUTE) == STRUCTURE_NODE_TYPE
            and data.get(IN_SCOPE_ATTRIBUTE) is True
        )
