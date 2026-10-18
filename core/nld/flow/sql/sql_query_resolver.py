from nld.connector.base import supports_cross_database_read
from nld.flow.definition import DataFlowDefinition, DataFlowStructurePredecessor
from nld.flow.sql.transformation.registry import resolve_rendering
from nld.service.nld_entity_registry import EntityTypeNames
from nld.structure import Structure, StructureNamespaceMapping
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


def resolve_input_database_names(
    flow_definition: DataFlowDefinition,
) -> dict[str, str]:
    """Return the database each input's namespace is declared in.

    Keyed like the flow predecessors, e.g. ``{"orders": "SHARED_RAW"}``.
    An input whose namespace has no structure mapping is left out.
    """
    structure_config = (
        NldExecutionContext.require_current().project.structure_namespace_config
    )
    input_database_names: dict[str, str] = {}
    for key, predecessor in flow_definition.predecessors.items():
        mapping = structure_config.find_mapping(
            namespace=predecessor.full_path.namespace,
        )
        if mapping is not None:
            input_database_names[key] = mapping.database_name
    return input_database_names


def _resolve_source_table_paths(
    flow_definition: DataFlowDefinition,
    source_predecessor_key: str | None = None,
) -> dict[str, str]:
    """Resolve source table paths from the structure config.

    Uses the structure config mapping to resolve the deploy schema
    for each predecessor's namespace, then combines it with the
    structure name to build the fully qualified table path. An input
    whose namespace maps to another database than the target's is
    read as ``database.schema.table``, e.g. ``SHARED_RAW.RAW.ORDERS``.
    """
    predecessors = flow_definition.predecessors
    if not predecessors:
        return {}
    if source_predecessor_key is not None:
        predecessors = {source_predecessor_key: predecessors[source_predecessor_key]}

    target_mapping = _find_target_mapping(flow_definition)
    return {
        key: _resolve_source_table_path(
            flow_definition=flow_definition,
            predecessor=predecessor,
            predecessor_key=key,
            target_mapping=target_mapping,
        )
        for key, predecessor in predecessors.items()
    }


def _find_target_mapping(
    flow_definition: DataFlowDefinition,
) -> StructureNamespaceMapping | None:
    """Return the structure mapping of the flow's target namespace, if any."""
    if flow_definition.target_structure is None:
        return None
    context = NldExecutionContext.require_current()
    return context.project.structure_namespace_config.find_mapping(
        namespace=flow_definition.target_structure.namespace,
    )


def _resolve_source_table_path(
    flow_definition: DataFlowDefinition,
    predecessor: DataFlowStructurePredecessor,
    predecessor_key: str,
    target_mapping: StructureNamespaceMapping | None,
) -> str:
    """Build the table path one input is read from.

    Both databases are the declared namespace ones, never the live
    connection's: the declarations do not change with the environment
    while the connection profiles do, so an input declared in the
    target's database keeps resolving against the connection.

    Raises:
        ValueError: if the input lives in another database than the
            target and the target engine cannot read across databases.
    """
    context = NldExecutionContext.require_current()
    mapping = context.project.structure_namespace_config.get_mapping(
        namespace=predecessor.full_path.namespace,
    )
    table_path = f"{mapping.schema_name}.{predecessor.full_path.entity_name}"
    if (
        target_mapping is None
        or mapping.database_name.lower() == target_mapping.database_name.lower()
    ):
        return table_path

    connector_type = _resolve_target_connector_type(
        flow_definition=flow_definition,
        target_mapping=target_mapping,
    )
    if not supports_cross_database_read(connector_type):
        raise ValueError(
            f"Flow '{flow_definition.name}' reads input '{predecessor_key}' "
            f"from database '{mapping.database_name}' while its target lives "
            f"in database '{target_mapping.database_name}': the "
            f"'{connector_type or 'unknown'}' engine cannot read across "
            f"databases."
        )
    return f"{mapping.database_name}.{table_path}"


def _resolve_target_connector_type(
    flow_definition: DataFlowDefinition,
    target_mapping: StructureNamespaceMapping,
) -> str | None:
    """Resolve the engine the flow query runs on.

    Most structures do not declare their connector type, so the type of
    the target namespace's default connection is used in that case.
    """
    target_structure = flow_definition.resolve_target_structure()
    if target_structure.connector_type is not None:
        return target_structure.connector_type
    connection_configs = NldExecutionContext.require_current().connection_configs
    connection_name = target_mapping.default_connection_name
    if connection_name not in connection_configs.get_connection_names():
        return None
    return connection_configs.get_connection_config(connection_name).type
