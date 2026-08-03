from collections.abc import Callable
from typing import Any

import click

from nld.logging import EventLevel
from nld.utils import decorator_utils

_LOG_LEVEL_CHOICES = [
    level.name for level in EventLevel if level.name not in ("FATAL", "TEST", "WARN")
]

log_level = click.option(
    "--log",
    "log_level",
    type=click.Choice(
        _LOG_LEVEL_CHOICES,
        case_sensitive=False,
    ),
    default="INFO",
    required=False,
    help="Set the log level (default: INFO)",
)

nld_root_folder_path = click.option(
    "--root-folder-path",
    type=str,
    envvar=None,
    help="NLD Root Folder Path",
    default=None,
    required=False,
)

connection_name = click.option(
    "--connection-name",
    type=str,
    envvar=None,
    help="Connection name to use",
    default=None,
    required=True,
)
profile_name = click.option(
    "--profile-name",
    type=str,
    envvar=None,
    help="Profile name to use",
    default=None,
    required=False,
)

specific_connection_params = decorator_utils.composed(connection_name, profile_name)

process_name = click.option(
    "--process",
    required=True,
    help="Name of the process",
)

structure = click.option(
    "--structure",
    required=True,
    help="Structure name inside the structure folder",
)


output_folder_name_not_required = click.option(
    "--output-folder-name",
    required=False,
    default=None,
    help="Optional output folder name",
)

namespace = click.option(
    "--namespace",
    type=str,
    required=False,
    default=None,
    help="Dot-separated namespace to organize assets (e.g. 'source.raw')",
)

output_inside_project = click.option(
    "--output-in-project",
    help="Output inside the project",
    is_flag=True,
    envvar=None,
    default=False,
    required=False,
)


def override_output_folder_path(
    file_name_hint: str = "The file name is fixed per command.",
) -> Callable[[Any], Any]:
    """Build the standard ``--override-output-folder-path`` option.

    Every command that writes a result file exposes this flag with the same
    spelling, type and default; only the sentence naming the produced file
    differs, which callers supply as ``file_name_hint``. Defining it once
    here keeps the file-output convention identical across command groups.

    Args:
        file_name_hint: Sentence appended to the help text describing which
            file the command writes into the folder.

    Returns:
        The click option decorator to apply to a command.
    """
    return click.option(
        "--override-output-folder-path",
        "override_output_folder_path",
        type=click.Path(file_okay=False, writable=True),
        required=False,
        default=None,
        help=(
            "Folder to write the result into, instead of a timestamped "
            f"folder under `output/`. {file_name_hint}"
        ),
    )
