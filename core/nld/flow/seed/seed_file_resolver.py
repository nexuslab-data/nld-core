import csv
import os

from nld.pydantic import SEEDS_FOLDER_NAME, NldEntityLayout


def resolve_seed_file_path(
    entities_root_folder_path: str,
    namespace: str,
    seed_name: str,
    entity_layout: NldEntityLayout | None = None,
) -> str:
    """Resolve the filesystem path to a CSV seed file.

    Builds the path:
        <entities_root>/seeds/<namespace_as_path>/<seed_name>.csv
    where namespace dots are converted to path separators, or the namespace
    folder equivalent when the namespace belongs to a namespace folder.

    Args:
        entities_root_folder_path: root folder of the project entities.
        namespace: dot-separated namespace (e.g. "reference"), or "." for root.
        seed_name: the name of the seed, matching the structure entity name.
        entity_layout: layout of the project entities; type first when None.

    Returns:
        Absolute path to the CSV seed file.

    Raises:
        FileNotFoundError: if the resolved CSV file does not exist.
    """
    layout = entity_layout if entity_layout is not None else NldEntityLayout()
    seed_file_path = os.path.join(
        layout.get_entity_directory(
            entities_root_folder_path=entities_root_folder_path,
            entity_folder_name=SEEDS_FOLDER_NAME,
            namespace=namespace,
        ),
        f"{seed_name}.csv",
    )

    if not os.path.isfile(seed_file_path):
        raise FileNotFoundError(
            f"Seed CSV file not found at expected path: {seed_file_path}"
        )

    return seed_file_path


def load_seed_file_content(seed_file_path: str) -> list[dict[str, str]]:
    """Read a CSV seed file and return its rows as a list of dicts.

    Args:
        seed_file_path: absolute path to the CSV seed file.

    Returns:
        List of row dicts keyed by column name, all values as strings.

    Raises:
        ValueError: if the file is empty or has no data rows.
    """
    with open(seed_file_path, newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        rows = list(reader)

    if not rows:
        raise ValueError(
            f"Seed CSV file is empty or has no data rows: {seed_file_path}"
        )

    return rows
