from collections.abc import Callable
from typing import Any

import click

from nld.parameters import ExecutionParameterDefinition
from nld.utils.string_utils import camel_to_kebab


def get_click_param_from_execution_param_definition(
    execution_param_definition: ExecutionParameterDefinition,
) -> Callable[..., Any]:
    click_type = (
        click.Choice(execution_param_definition.allowed_values)
        if execution_param_definition.allowed_values
        and len(execution_param_definition.allowed_values) > 0
        else execution_param_definition.data_type
    )
    return click.option(
        f"--{camel_to_kebab(execution_param_definition.name)}",
        type=click_type,
        required=execution_param_definition.mandatory,
        default=execution_param_definition.default_value,
        help=execution_param_definition.help_text,
    )
