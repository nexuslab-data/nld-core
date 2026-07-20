from typing import TYPE_CHECKING

import networkx as nx

from nld.flow.graph.data_flow_graph import (
    FLOW_NODE_TYPE,
    STRUCTURE_NODE_TYPE,
    DataFlowGraph,
    build_node_id,
    strip_node_type_prefix,
)
from nld.pydantic import NldBaseModel, NldNamespace

from .ownership import FlowOwner, OwnerBase, StructureOwner

if TYPE_CHECKING:
    from nld.service.nld_entity_registry import NldEntityRegistry

STRUCTURE_OWNER_ENTITY_TYPE = "structure_owner"
FLOW_OWNER_ENTITY_TYPE = "flow_owner"


class ResolvedOwner(NldBaseModel):
    """A single resolved owner, annotated with how it was resolved."""

    team: str
    contact: str | None = None
    source_namespace: str
    via: str | None = None
    """How the owner was reached: ``None`` for a direct namespace declaration,
    ``flow:<flow_id>`` for a producing flow, ``lineage:<structure_id>`` for an
    upstream source reached by walking the dependency graph."""


def _split_entity_id(entity_id: str) -> tuple[str, str]:
    """Split a full entity id ``namespace.name`` into ``(namespace, name)``.

    Structure and flow names never contain dots, so the name is the segment
    after the last dot; an id with no dot lives at the root namespace.
    """
    namespace, separator, name = entity_id.rpartition(".")
    if not separator:
        return NldNamespace.ROOT_VALUE, entity_id
    return namespace, name


def _owners_in_hierarchy(
    registry: "NldEntityRegistry",
    entity_type: str,
    model_cls: type[OwnerBase],
    namespace: str | None,
) -> list[tuple[NldNamespace, OwnerBase]]:
    """Return ``(namespace, owner)`` pairs along the hierarchy, deepest first."""
    target = NldNamespace(namespace) if namespace is not None else NldNamespace(".")
    if entity_type not in registry.entities:
        return []
    storage = registry.entities[entity_type]
    pairs: list[tuple[NldNamespace, OwnerBase]] = []
    for level_namespace in target.hierarchy:
        for model in storage.get(level_namespace, {}).values():
            if isinstance(model, model_cls):
                pairs.append((level_namespace, model))
    pairs.sort(key=lambda item: item[0].depth, reverse=True)
    return pairs


def _nearest_owner(
    pairs: list[tuple[NldNamespace, OwnerBase]],
    name: str | None,
) -> tuple[NldNamespace, OwnerBase] | None:
    """Pick the effective owner from hierarchy pairs (deepest first).

    A per-entity override (``targets`` includes ``name``) always wins over the
    namespace default (``targets`` omitted); among each, the nearest namespace
    wins.
    """
    if name is not None:
        for level_namespace, owner in pairs:
            if owner.targets and name in owner.targets:
                return level_namespace, owner
    for level_namespace, owner in pairs:
        if not owner.targets:
            return level_namespace, owner
    return None


def resolve_structure_owner_declaration(
    registry: "NldEntityRegistry",
    namespace: str | None = None,
    structure_name: str | None = None,
) -> tuple[NldNamespace, StructureOwner] | None:
    """Effective structure-owner declaration for a structure, or None.

    A declaration targeting ``structure_name`` wins over the nearest namespace
    default.
    """
    pairs = _owners_in_hierarchy(
        registry=registry,
        entity_type=STRUCTURE_OWNER_ENTITY_TYPE,
        model_cls=StructureOwner,
        namespace=namespace,
    )
    result = _nearest_owner(pairs=pairs, name=structure_name)
    if result is None:
        return None
    level_namespace, owner = result
    assert isinstance(owner, StructureOwner)
    return level_namespace, owner


def resolve_flow_owner_declaration(
    registry: "NldEntityRegistry",
    namespace: str | None = None,
    flow_name: str | None = None,
) -> tuple[NldNamespace, FlowOwner] | None:
    """Effective flow-owner declaration for a flow, or None.

    A declaration targeting ``flow_name`` wins over the nearest namespace default.
    """
    pairs = _owners_in_hierarchy(
        registry=registry,
        entity_type=FLOW_OWNER_ENTITY_TYPE,
        model_cls=FlowOwner,
        namespace=namespace,
    )
    result = _nearest_owner(pairs=pairs, name=flow_name)
    if result is None:
        return None
    level_namespace, owner = result
    assert isinstance(owner, FlowOwner)
    return level_namespace, owner


def build_flow_graph(registry: "NldEntityRegistry") -> DataFlowGraph:
    """Build the full data-flow dependency graph used for lineage resolution."""
    return DataFlowGraph(flow_dict=registry.get_data_flow_definition_dict())


def resolve_flow_owner(
    registry: "NldEntityRegistry",
    flow_id: str,
) -> ResolvedOwner | None:
    """Resolve the technical owner of a flow id ``namespace.name``."""
    namespace, flow_name = _split_entity_id(flow_id)
    declaration = resolve_flow_owner_declaration(
        registry=registry,
        namespace=namespace,
        flow_name=flow_name,
    )
    if declaration is None:
        return None
    source_namespace, owner = declaration
    return ResolvedOwner(
        team=owner.team,
        contact=owner.contact,
        source_namespace=str(source_namespace),
    )


def resolve_structure_data_owners(
    registry: "NldEntityRegistry",
    structure_id: str,
    graph: DataFlowGraph | None = None,
) -> list[ResolvedOwner]:
    """Resolve the data owner(s) of a structure.

    Axis A: if the structure (or its namespace) declares a structure owner, that
    nearest declaration wins and is returned alone. Axis B: otherwise walk the
    dependency graph upstream and return the union of the data owners of every
    upstream structure that does declare one (the sources).
    """
    namespace, structure_name = _split_entity_id(structure_id)
    direct = resolve_structure_owner_declaration(
        registry=registry,
        namespace=namespace,
        structure_name=structure_name,
    )
    if direct is not None:
        source_namespace, owner = direct
        return [
            ResolvedOwner(
                team=owner.team,
                contact=owner.contact,
                source_namespace=str(source_namespace),
            )
        ]

    if graph is None:
        graph = build_flow_graph(registry=registry)

    node_id = build_node_id(node_type=STRUCTURE_NODE_TYPE, entity_id=structure_id)
    if node_id not in graph.digraph:
        return []

    ancestors: set[str] = nx.ancestors(graph.digraph, source=node_id)  # type: ignore[no-untyped-call]
    collected: dict[str, ResolvedOwner] = {}
    for ancestor in sorted(ancestors):
        if graph.get_node_type(ancestor) != STRUCTURE_NODE_TYPE:
            continue
        upstream_id = strip_node_type_prefix(ancestor)
        upstream_namespace, upstream_name = _split_entity_id(upstream_id)
        upstream = resolve_structure_owner_declaration(
            registry=registry,
            namespace=upstream_namespace,
            structure_name=upstream_name,
        )
        if upstream is None:
            continue
        source_namespace, owner = upstream
        if owner.team in collected:
            continue
        collected[owner.team] = ResolvedOwner(
            team=owner.team,
            contact=owner.contact,
            source_namespace=str(source_namespace),
            via=f"lineage:{upstream_id}",
        )
    return [collected[team] for team in sorted(collected)]


def resolve_structure_technical_owners(
    registry: "NldEntityRegistry",
    structure_id: str,
    graph: DataFlowGraph | None = None,
) -> list[ResolvedOwner]:
    """Resolve the technical owner(s) of a structure via its producing flow(s).

    A source structure (produced by no in-scope flow) has no technical owner and
    yields an empty list.
    """
    if graph is None:
        graph = build_flow_graph(registry=registry)

    node_id = build_node_id(node_type=STRUCTURE_NODE_TYPE, entity_id=structure_id)
    if node_id not in graph.digraph:
        return []

    results: list[ResolvedOwner] = []
    seen_flows: set[str] = set()
    producing_nodes: list[str] = list(graph.digraph.predecessors(node_id))  # type: ignore[no-untyped-call]
    for predecessor in sorted(producing_nodes):
        if graph.get_node_type(predecessor) != FLOW_NODE_TYPE:
            continue
        flow_id = strip_node_type_prefix(predecessor)
        if flow_id in seen_flows:
            continue
        seen_flows.add(flow_id)
        flow_namespace, flow_name = _split_entity_id(flow_id)
        declaration = resolve_flow_owner_declaration(
            registry=registry,
            namespace=flow_namespace,
            flow_name=flow_name,
        )
        if declaration is None:
            continue
        source_namespace, owner = declaration
        results.append(
            ResolvedOwner(
                team=owner.team,
                contact=owner.contact,
                source_namespace=str(source_namespace),
                via=f"flow:{flow_id}",
            )
        )
    return results
