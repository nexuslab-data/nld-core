import csv
import os

from nld.pydantic import NldNamespace


def resolve_seed_file_path(
    entities_root_folder_path: str,
    namespace: str,
    seed_name: str,
) -> str:
    """Resolve the filesystem path to a CSV seed file.

    Builds the path:
        <entities_root>/seeds/<namespace_as_path>/<seed_name>.csv
    where namespace dots are converted to path separators.

    Args:
        entities_root_folder_path: root folder of the project entities.
        namespace: dot-separated namespace (e.g. "reference"), or "." for root.
        seed_name: the name of the seed, matching the structure entity name.

    Returns:
        Absolute path to the CSV seed file.

    Raises:
        FileNotFoundError: if the resolved CSV file does not exist.
    """
    ns = NldNamespace(namespace)
    path_parts = [entities_root_folder_path, "seeds"]

    if not ns.is_root:
        path_parts.append(ns.to_path())

    path_parts.append(f"{seed_name}.csv")

    seed_file_path = os.path.join(*path_parts)

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
