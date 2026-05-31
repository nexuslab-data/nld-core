from __future__ import annotations

import networkx as nx

from nld.flow.definition import NamespacedDataFlowDefinition

FLOW_NODE_TYPE: str = "flow"
STRUCTURE_NODE_TYPE: str = "structure"

NODE_TYPE_PREFIX_SEPARATOR: str = "."


def build_node_id(
    node_type: str,
    entity_id: str,
) -> str:
    """Build a graph node ID with a type prefix."""
    return f"{node_type}{NODE_TYPE_PREFIX_SEPARATOR}{entity_id}"


def strip_node_type_prefix(
    node_id: str,
) -> str:
    """Remove the type prefix from a graph node ID."""
    parts = node_id.split(NODE_TYPE_PREFIX_SEPARATOR, maxsplit=1)
    return parts[1] if len(parts) == 2 else node_id


class DataFlowGraph:
    """Directed acyclic graph of data flow definitions and structures.

    Wraps a networkx DiGraph where nodes are either flows or
    structures. Flow nodes store the NamespacedDataFlowDefinition
    as the ``"flow"`` attribute. All nodes carry a ``"node_type"``
    attribute (``"flow"`` or ``"structure"``). Edges link flows to
    their target structures and predecessor structures to flows.
    """

    FLOW_ATTRIBUTE: str = "flow"
    NODE_TYPE_ATTRIBUTE: str = "node_type"

    def __init__(
        self,
        flow_dict: dict[str, NamespacedDataFlowDefinition],
    ) -> None:
        self._digraph = nx.DiGraph()
        self._build(flow_dict=flow_dict)

    @classmethod
    def _from_digraph(
        cls,
        digraph: nx.DiGraph,
    ) -> DataFlowGraph:
        """Create a DataFlowGraph from an existing DiGraph."""
        instance = cls.__new__(cls)
        instance._digraph = digraph
        return instance

    @property
    def digraph(self) -> nx.DiGraph:
        """Return the underlying networkx DiGraph."""
        return self._digraph

    @property
    def flow_ids(self) -> list[str]:
        """Return all flow IDs sorted alphabetically."""
        return sorted(
            node_id
            for node_id, data in self._digraph.nodes(data=True)
            if data.get(self.NODE_TYPE_ATTRIBUTE) == FLOW_NODE_TYPE
        )

    @property
    def structure_ids(self) -> list[str]:
        """Return all structure IDs sorted alphabetically."""
        return sorted(
            node_id
            for node_id, data in self._digraph.nodes(data=True)
            if data.get(self.NODE_TYPE_ATTRIBUTE) == STRUCTURE_NODE_TYPE
        )

    @property
    def node_ids(self) -> list[str]:
        """Return all node IDs sorted alphabetically."""
        return sorted(self._digraph.nodes)

    def get_flow(
        self,
        flow_id: str,
    ) -> NamespacedDataFlowDefinition:
        """Retrieve the NamespacedDataFlowDefinition for a flow ID.

        Raises:
            KeyError: If the flow ID is not in the graph.
        """
        result: NamespacedDataFlowDefinition = self._digraph.nodes[flow_id][
            self.FLOW_ATTRIBUTE
        ]
        return result

    def get_node_type(
        self,
        node_id: str,
    ) -> str:
        """Return the node type for a given node ID.

        Raises:
            KeyError: If the node ID is not in the graph.
        """
        result: str = self._digraph.nodes[node_id][self.NODE_TYPE_ATTRIBUTE]
        return result

    def topological_sort(self) -> list[str]:
        """Return flow IDs in topological execution order.

        Structure nodes are filtered out so that only flows
        are returned. Independent nodes at the same level are
        sorted alphabetically for deterministic output.

        Raises:
            ValueError: If a cycle is detected.
        """
        try:
            generations = list(nx.topological_generations(self._digraph))
        except nx.NetworkXUnfeasible:
            cycle = nx.find_cycle(self._digraph)
            cycle_nodes = sorted({node for edge in cycle for node in edge[:2]})
            raise ValueError(
                f"Cycle detected among flows: {', '.join(cycle_nodes)}"
            ) from None

        flow_id_set = set(self.flow_ids)
        result: list[str] = []
        for generation in generations:
            result.extend(
                sorted(node_id for node_id in generation if node_id in flow_id_set)
            )
        return result

    def get_edges(self) -> list[tuple[str, str, str, str]]:
        """Return all graph edges as typed tuples.

        Each tuple contains (source_type, source_id, target_type,
        target_id) with the node type prefix stripped from IDs.

        Returns:
            List of (source_type, source_id, target_type, target_id)
            tuples for every edge in the graph.
        """
        edges: list[tuple[str, str, str, str]] = []
        for source_node, target_node in self._digraph.edges():
            source_type = self._digraph.nodes[source_node][self.NODE_TYPE_ATTRIBUTE]
            source_id = strip_node_type_prefix(source_node)
            target_type = self._digraph.nodes[target_node][self.NODE_TYPE_ATTRIBUTE]
            target_id = strip_node_type_prefix(target_node)
            edges.append((source_type, source_id, target_type, target_id))
        return edges

    def get_transitive_dependents(
        self,
        flow_id: str,
    ) -> set[str]:
        """Return all transitive flow dependents of a flow.

        The returned set does not include the flow_id itself
        and only contains flow nodes, not structure nodes.

        Returns:
            Empty set if the flow_id is not in the graph.
        """
        if flow_id not in self._digraph:
            return set()
        all_descendants: set[str] = nx.descendants(self._digraph, source=flow_id)  # type: ignore[no-untyped-call]
        flow_id_set = set(self.flow_ids)
        result = all_descendants & flow_id_set
        return result

    def resolve_node_id(
        self,
        name: str,
        namespace: str | None = None,
        node_type: str | None = None,
    ) -> str:
        """Resolve a node name to its full graph node ID.

        Args:
            name: The entity name without namespace or type prefix.
            namespace: Optional namespace prefix.
            node_type: Optional filter by node type.

        Raises:
            KeyError: If no matching node is found.
            ValueError: If multiple nodes match without namespace.
        """
        if namespace is not None and node_type is not None:
            candidate = build_node_id(
                node_type=node_type,
                entity_id=f"{namespace}.{name}",
            )
            if candidate not in self._digraph:
                raise KeyError(
                    f"Node '{node_type}.{namespace}.{name}' not found in the graph"
                )
            return candidate

        if namespace is not None:
            entity_id = f"{namespace}.{name}"
            candidates: list[str] = [
                node_id
                for node_id in self._digraph.nodes
                if strip_node_type_prefix(node_id=node_id) == entity_id
            ]
        else:
            candidates = []
            for node_id, data in self._digraph.nodes(data=True):
                if node_type is not None:
                    if data.get(self.NODE_TYPE_ATTRIBUTE) != node_type:
                        continue
                entity_id_part = strip_node_type_prefix(node_id=node_id)
                parts = entity_id_part.split(".", maxsplit=1)
                entity_name = parts[1] if len(parts) == 2 else parts[0]
                if entity_name == name:
                    candidates.append(node_id)

        if len(candidates) == 0:
            raise KeyError(f"Node with name '{name}' not found in the graph")
        if len(candidates) > 1:
            raise ValueError(
                f"Ambiguous name '{name}' matches multiple nodes:"
                f" {', '.join(sorted(candidates))}."
                f" Use --namespace to disambiguate."
            )
        return candidates[0]

    def get_lineage_subgraph(
        self,
        node_id: str,
        upstream: bool = True,
        downstream: bool = True,
    ) -> DataFlowGraph:
        """Return a subgraph containing the lineage of a node.

        Args:
            node_id: The node to compute lineage for.
            upstream: Include ancestor nodes.
            downstream: Include descendant nodes.

        Raises:
            KeyError: If the node_id is not in the graph.
        """
        if node_id not in self._digraph:
            raise KeyError(f"Node '{node_id}' not found in the graph")

        lineage_nodes: set[str] = {node_id}

        if upstream:
            lineage_nodes |= nx.ancestors(self._digraph, source=node_id)  # type: ignore[no-untyped-call]
        if downstream:
            lineage_nodes |= nx.descendants(self._digraph, source=node_id)  # type: ignore[no-untyped-call]

        subgraph: nx.DiGraph = self._digraph.subgraph(lineage_nodes).copy()  # type: ignore[no-untyped-call]
        return DataFlowGraph._from_digraph(digraph=subgraph)

    def get_namespace_lineage_subgraph(
        self,
        namespace: str,
        upstream: bool = True,
        downstream: bool = True,
    ) -> DataFlowGraph:
        """Return a subgraph containing the lineage of all nodes in a namespace.

        Collects every node whose entity ID starts with the given namespace,
        then computes the union of their individual lineages.

        Args:
            namespace: The namespace to filter on.
            upstream: Include ancestor nodes.
            downstream: Include descendant nodes.

        Raises:
            KeyError: If no nodes belong to the namespace.
        """
        if namespace == ".":
            full_copy: nx.DiGraph = self._digraph.copy()
            return DataFlowGraph._from_digraph(digraph=full_copy)

        namespace_prefix = f"{namespace}."
        namespace_nodes: set[str] = {
            node_id
            for node_id in self._digraph.nodes
            if strip_node_type_prefix(node_id=node_id).startswith(namespace_prefix)
        }

        if not namespace_nodes:
            raise KeyError(f"No nodes found for namespace '{namespace}'")

        lineage_nodes: set[str] = set(namespace_nodes)

        for node_id in namespace_nodes:
            if upstream:
                lineage_nodes |= nx.ancestors(self._digraph, source=node_id)  # type: ignore[no-untyped-call]
            if downstream:
                lineage_nodes |= nx.descendants(self._digraph, source=node_id)  # type: ignore[no-untyped-call]

        subgraph: nx.DiGraph = self._digraph.subgraph(lineage_nodes).copy()  # type: ignore[no-untyped-call]
        return DataFlowGraph._from_digraph(digraph=subgraph)

    def get_scoped_subgraph(
        self,
        name: str | None = None,
        namespace: str | None = None,
        node_type: str | None = None,
        upstream: bool = False,
        downstream: bool = False,
    ) -> DataFlowGraph:
        """Return a subgraph scoped by name/namespace and lineage.

        When ``name`` is provided, resolves the node and returns its
        lineage subgraph. When only ``namespace`` is given, returns
        the namespace lineage subgraph. When neither is provided,
        returns the full graph.

        Args:
            name: entity name to scope on.
            namespace: namespace to scope on.
            node_type: node type filter (e.g. "flow", "structure").
            upstream: include upstream lineage.
            downstream: include downstream lineage.

        Returns:
            A DataFlowGraph containing only the scoped nodes.
        """
        if name is not None:
            node_id = self.resolve_node_id(
                name=name,
                namespace=namespace,
                node_type=node_type,
            )
            return self.get_lineage_subgraph(
                node_id=node_id,
                upstream=upstream,
                downstream=downstream,
            )

        if namespace is not None:
            return self.get_namespace_lineage_subgraph(
                namespace=namespace,
                upstream=upstream,
                downstream=downstream,
            )

        return self

    def _build(
        self,
        flow_dict: dict[str, NamespacedDataFlowDefinition],
    ) -> None:
        """Populate the graph from a flow dictionary."""
        self._add_nodes(flow_dict=flow_dict)
        self._add_edges(flow_dict=flow_dict)

    def _add_nodes(
        self,
        flow_dict: dict[str, NamespacedDataFlowDefinition],
    ) -> None:
        """Add flow and structure nodes to the graph."""
        structure_entity_ids: set[str] = set()

        for namespaced_flow in flow_dict.values():
            flow_definition = namespaced_flow.model
            flow_node_id = build_node_id(
                node_type=FLOW_NODE_TYPE,
                entity_id=namespaced_flow.id,
            )
            self._digraph.add_node(
                flow_node_id,
                **{
                    self.FLOW_ATTRIBUTE: namespaced_flow,
                    self.NODE_TYPE_ATTRIBUTE: FLOW_NODE_TYPE,
                },
            )

            if flow_definition.target_structure is not None:
                structure_entity_ids.add(str(flow_definition.target_structure))

            if flow_definition.predecessors:
                for predecessor in flow_definition.predecessors.values():
                    structure_entity_ids.add(str(predecessor.full_path))

        for entity_id in structure_entity_ids:
            structure_node_id = build_node_id(
                node_type=STRUCTURE_NODE_TYPE,
                entity_id=entity_id,
            )
            self._digraph.add_node(
                structure_node_id,
                **{self.NODE_TYPE_ATTRIBUTE: STRUCTURE_NODE_TYPE},
            )

    def _add_edges(
        self,
        flow_dict: dict[str, NamespacedDataFlowDefinition],
    ) -> None:
        """Add edges linking flows to structures.

        Each flow with a target_structure gets an edge from the
        flow to that structure. Each predecessor structure gets
        an edge from the structure to the consuming flow.
        """
        for namespaced_flow in flow_dict.values():
            flow_definition = namespaced_flow.model
            flow_node_id = build_node_id(
                node_type=FLOW_NODE_TYPE,
                entity_id=namespaced_flow.id,
            )

            if flow_definition.target_structure is not None:
                target_node_id = build_node_id(
                    node_type=STRUCTURE_NODE_TYPE,
                    entity_id=str(flow_definition.target_structure),
                )
                self._digraph.add_edge(
                    flow_node_id,
                    target_node_id,
                )

            if flow_definition.predecessors:
                for predecessor in flow_definition.predecessors.values():
                    predecessor_node_id = build_node_id(
                        node_type=STRUCTURE_NODE_TYPE,
                        entity_id=str(predecessor.full_path),
                    )
                    self._digraph.add_edge(
                        predecessor_node_id,
                        flow_node_id,
                    )
