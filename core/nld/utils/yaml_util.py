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


class IndentedSequenceSafeDumper(yaml.SafeDumper):
    """Safe dumper that indents block sequences under their parent key.

    PyYAML writes ``key:`` followed by ``- item`` at the same indentation,
    while hand-written NLD entity files indent the items. Matching that
    style keeps the diff of a rewritten entity file to the real changes.
    """

    def increase_indent(
        self,
        flow: bool = False,
        indentless: bool = False,
    ) -> None:
        """Never emit indentless sequences."""
        super().increase_indent(
            flow,
            False,
        )


def dump_dict_to_entity_yaml_str(data: dict[str, Any]) -> str:
    """Dump a dict to a YAML string in the hand-written entity file style.

    Keys keep their insertion order, sequences are indented under their
    parent key and long strings are never folded over several lines.
    """
    return yaml.dump(
        data,
        Dumper=IndentedSequenceSafeDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=4096,
    )
