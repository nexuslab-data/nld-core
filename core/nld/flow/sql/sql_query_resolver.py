from nld.flow.definition import DataFlowDefinition
from nld.flow.sql.transformation.registry import resolve_rendering
from nld.service.nld_entity_registry import EntityTypeNames
from nld.structure import Structure
from nld.task.context.context import NldExecutionContext


def render_sql_from_flow_definition(
    flow_definition: DataFlowDefinition,
    source_predecessor_key: str | None = None,
) -> str:
    """Render a SQL SELECT query from flow metadata.

    Resolves source structures, table paths, target structure and
    dialect from the flow definition, then delegates to the
    appropriate rendering strategy.

    Args:
        flow_definition: the flow definition containing predecessors,
            target structure, and mapping configuration.
        source_predecessor_key: optional key to restrict rendering
            to a single predecessor.

    Returns:
        The rendered SQL query as a string.
    """
    source_structures = _resolve_source_structures(
        flow_definition=flow_definition,
        source_predecessor_key=source_predecessor_key,
    )
    source_table_paths = _resolve_source_table_paths(
        flow_definition=flow_definition,
        source_predecessor_key=source_predecessor_key,
    )

    dialect = flow_definition.resolve_target_dialect()
    rendering = resolve_rendering(flow_definition)

    target_structure = (
        flow_definition.resolve_target_structure()
        if flow_definition.target_structure is not None
        else None
    )

    return rendering.render(
        source_structures=source_structures,
        source_table_paths=source_table_paths,
        target_from_sources_mapping=flow_definition.target_from_sources_mapping,
        target_structure=target_structure,
        dialect=dialect,
    )


def _resolve_source_structures(
    flow_definition: DataFlowDefinition,
    source_predecessor_key: str | None = None,
) -> dict[str, Structure]:
    """Resolve source structures from flow predecessors."""
    predecessors = flow_definition.predecessors
    if not predecessors:
        raise ValueError(
            f"Flow '{flow_definition.name}' has no predecessors defined. "
            f"At least one predecessor is required for SQL rendering."
        )

    if source_predecessor_key is not None:
        predecessor = predecessors.get(source_predecessor_key)
        if predecessor is None:
            raise ValueError(
                f"Predecessor key '{source_predecessor_key}' "
                f"not found in flow '{flow_definition.name}'. "
                f"Available keys: {list(predecessors.keys())}"
            )
        structure = predecessor.full_path.resolve(
            entity_type=EntityTypeNames.STRUCTURE,
        )
        return {source_predecessor_key: structure}

    result: dict[str, Structure] = {}
    for key, predecessor in predecessors.items():
        result[key] = predecessor.full_path.resolve(
            entity_type=EntityTypeNames.STRUCTURE,
        )
    return result


def _resolve_source_table_paths(
    flow_definition: DataFlowDefinition,
    source_predecessor_key: str | None = None,
) -> dict[str, str]:
    """Resolve source table paths from the structure config.

    Uses the structure config mapping to resolve the deploy schema
    for each predecessor's namespace, then combines it with the
    structure name to build the fully qualified table path.
    """
    predecessors = flow_definition.predecessors
    if not predecessors:
        return {}

    context = NldExecutionContext.require_current()
    structure_config = context.project.structure_namespace_config

    if source_predecessor_key is not None:
        predecessor = predecessors[source_predecessor_key]
        namespace = predecessor.full_path.namespace
        entity_name = predecessor.full_path.entity_name
        mapping = structure_config.get_mapping(namespace=namespace)
        return {source_predecessor_key: f"{mapping.schema_name}.{entity_name}"}

    result: dict[str, str] = {}
    for key, predecessor in predecessors.items():
        namespace = predecessor.full_path.namespace
        entity_name = predecessor.full_path.entity_name
        mapping = structure_config.get_mapping(namespace=namespace)
        result[key] = f"{mapping.schema_name}.{entity_name}"

    return result
