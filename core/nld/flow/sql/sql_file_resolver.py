import os

from nld.pydantic import FLOWS_FOLDER_NAME, NldEntityLayout


def _build_sql_file_path(
    entities_root_folder_path: str,
    namespace: str,
    flow_name: str,
    entity_layout: NldEntityLayout | None = None,
) -> str:
    """Build the expected filesystem path to a SQL file for a given flow."""
    layout = entity_layout if entity_layout is not None else NldEntityLayout()
    return os.path.join(
        layout.get_entity_directory(
            entities_root_folder_path=entities_root_folder_path,
            entity_folder_name=FLOWS_FOLDER_NAME,
            namespace=namespace,
        ),
        f"{flow_name}.sql",
    )


def resolve_sql_file_path(
    entities_root_folder_path: str,
    namespace: str,
    flow_name: str,
    entity_layout: NldEntityLayout | None = None,
) -> str:
    """Resolve the filesystem path to a SQL file for a given flow.

    Builds the path: <entities_root>/flows/<namespace_as_path>/<flow_name>.sql
    where namespace dots are converted to path separators, or the namespace
    folder equivalent when the namespace belongs to a namespace folder.

    Args:
        entities_root_folder_path: root folder of the project entities
        namespace: dot-separated namespace (e.g. "source.raw"), or "." for root
        flow_name: the name of the flow
        entity_layout: layout of the project entities; type first when None

    Returns:
        Absolute path to the SQL file.

    Raises:
        FileNotFoundError: if the resolved SQL file does not exist.
    """
    sql_file_path = _build_sql_file_path(
        entities_root_folder_path=entities_root_folder_path,
        namespace=namespace,
        flow_name=flow_name,
        entity_layout=entity_layout,
    )

    if not os.path.isfile(sql_file_path):
        raise FileNotFoundError(f"SQL file not found at expected path: {sql_file_path}")

    return sql_file_path


def try_resolve_sql_file_path(
    entities_root_folder_path: str,
    namespace: str,
    flow_name: str,
    entity_layout: NldEntityLayout | None = None,
) -> str | None:
    """Resolve the filesystem path to a SQL file, returning None if absent.

    Same path logic as resolve_sql_file_path but returns None
    instead of raising FileNotFoundError when the file does not exist.
    """
    sql_file_path = _build_sql_file_path(
        entities_root_folder_path=entities_root_folder_path,
        namespace=namespace,
        flow_name=flow_name,
        entity_layout=entity_layout,
    )

    if not os.path.isfile(sql_file_path):
        return None

    return sql_file_path


def load_sql_file_content(sql_file_path: str) -> str:
    """Read and return the stripped SQL content from a file.

    Args:
        sql_file_path: absolute path to the SQL file

    Returns:
        The SQL content as a stripped string.

    Raises:
        ValueError: if the file is empty after stripping.
    """
    with open(sql_file_path) as file:
        content = file.read().strip()

    if not content:
        raise ValueError(f"SQL file is empty: {sql_file_path}")

    return content
