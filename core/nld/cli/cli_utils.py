from types import ModuleType

import click
import click.core

from nld.utils.inspect_utils import (
    extract_functions_from_command_module,
)


def add_commands_from_modules(
    cli: click.core.Group, command_module: ModuleType, command_prefix: str = ""
) -> None:
    commands = extract_functions_from_command_module(
        command_module, command_prefix, click.core.Command
    )
    groups = extract_functions_from_command_module(
        command_module, command_prefix, click.core.Group
    )

    for method in commands + groups:
        if method.name == cli.name:
            continue
        cli.add_command(method)
