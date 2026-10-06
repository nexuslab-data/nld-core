import hashlib
import inspect
import json

from nld.flow.definition.flow_definition import DataFlowDefinition
from nld.flow.sql.sql_file_resolver import resolve_sql_file_path
from nld.pydantic import NldEntityLayout


def build_flow_yaml_snapshot_json(flow_definition: DataFlowDefinition) -> str:
    """Serialize the flow definition to a JSON snapshot for audit purposes."""
    return json.dumps(
        flow_definition.model_dump(
            mode="json",
            exclude_none=True,
        ),
        default=str,
    )


def compute_flow_yaml_hash(flow_definition: DataFlowDefinition) -> str:
    """Compute a SHA-256 hash of the flow definition YAML content.

    Excludes runtime-only fields (cached task module, resolved references)
    by serializing only the Pydantic model fields to deterministic JSON.

    Args:
        flow_definition: the flow definition to hash

    Returns:
        Uppercase hex SHA-256 digest.
    """
    model_dict = flow_definition.model_dump(
        mode="json",
        exclude_none=True,
    )
    content = json.dumps(
        model_dict,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest().upper()


def compute_flow_sql_hash(
    entities_root_folder_path: str,
    namespace: str,
    flow_name: str,
    entity_layout: NldEntityLayout | None = None,
) -> str | None:
    """Compute a SHA-256 hash of the flow's SQL file content.

    Returns None if no SQL file exists for this flow.

    Args:
        entities_root_folder_path: root folder of the project entities
        namespace: dot-separated namespace
        flow_name: the name of the flow
        entity_layout: layout of the project entities; type first when None

    Returns:
        Uppercase hex SHA-256 digest, or None if no SQL file.
    """
    try:
        sql_path = resolve_sql_file_path(
            entities_root_folder_path=entities_root_folder_path,
            namespace=namespace,
            flow_name=flow_name,
            entity_layout=entity_layout,
        )
    except FileNotFoundError:
        return None

    with open(sql_path) as fh:
        content = fh.read()

    return hashlib.sha256(content.encode("utf-8")).hexdigest().upper()


def compute_flow_python_hash(
    flow_definition: DataFlowDefinition,
    namespace: str,
    entity_layout: NldEntityLayout | None,
    additional_task_paths: list[str] | None,
    additional_flow_task_types: dict[str, str] | None = None,
) -> str:
    """Compute a SHA-256 hash of the flow's Python task class source.

    Uses importlib-based resolution via resolve_task_module to locate
    the task class, then hashes only the class source code.

    Args:
        flow_definition: the flow definition
        namespace: dot-separated namespace
        entity_layout: project entity layout
        additional_task_paths: optional additional module search paths
        additional_flow_task_types: user-configured task type mappings

    Returns:
        Uppercase hex SHA-256 digest.
    """
    _module, task_class = flow_definition.resolve_task_module(
        namespace=namespace,
        entity_layout=entity_layout,
        additional_task_paths=additional_task_paths,
        additional_flow_task_types=additional_flow_task_types,
    )

    try:
        source = inspect.getsource(task_class)
    except OSError as exc:
        raise OSError(
            f"Cannot retrieve source for task class "
            f"'{task_class.__qualname__}' in flow '{flow_definition.name}'."
        ) from exc

    return hashlib.sha256(source.encode("utf-8")).hexdigest().upper()


def compute_flow_definition_hash(
    flow_definition: DataFlowDefinition,
    entities_root_folder_path: str,
    namespace: str,
    entity_layout: NldEntityLayout | None,
    additional_task_paths: list[str] | None = None,
    additional_flow_task_types: dict[str, str] | None = None,
) -> str:
    """Compute a combined SHA-256 hash from YAML, SQL, and Python hashes.

    The combined hash changes whenever any of the three components change.

    Args:
        flow_definition: the flow definition
        entities_root_folder_path: root folder of the project entities
        namespace: dot-separated namespace
        entity_layout: project entity layout
        additional_task_paths: optional additional module search paths
        additional_flow_task_types: user-configured task type mappings

    Returns:
        Uppercase hex SHA-256 digest.
    """
    yaml_hash = compute_flow_yaml_hash(flow_definition=flow_definition)
    sql_hash = compute_flow_sql_hash(
        entities_root_folder_path=entities_root_folder_path,
        namespace=namespace,
        flow_name=flow_definition.name,
        entity_layout=entity_layout,
    )
    python_hash = compute_flow_python_hash(
        flow_definition=flow_definition,
        namespace=namespace,
        entity_layout=entity_layout,
        additional_task_paths=additional_task_paths,
        additional_flow_task_types=additional_flow_task_types,
    )

    combined = f"{yaml_hash}:{sql_hash or ''}:{python_hash}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest().upper()
