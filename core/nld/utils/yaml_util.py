from typing import Any

import yaml

YAML_FILE_STANDARD_REGEX = r".*\.ya?ml$"


def load_yaml_file_into_dict(file_path: str) -> Any:
    """Loads a yaml file into a dictionary.

    Args:
        file_path: The local file path.

    Returns:
        A dictionary loaded with all the yaml file content.
    """
    with open(file_path) as file:
        return yaml.safe_load(file)


def dump_dict_to_yaml(
    data: dict[str, Any],
    file_path: str,
    *,
    sort_keys: bool = False,
    allow_unicode: bool = True,
    default_flow_style: bool = False,
) -> None:
    """Dump a Python dict to a YAML file."""
    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(
            data,
            f,
            Dumper=yaml.SafeDumper,
            sort_keys=sort_keys,
            allow_unicode=allow_unicode,
            default_flow_style=default_flow_style,
        )
