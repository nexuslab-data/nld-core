import logging
from collections.abc import Callable
from typing import Any

import click

from nld.cli import params, requires
from nld.utils import decorator_utils


def nld_command(
    command_name: str,
    group: click.Group | None = None,
    logger_formatter: logging.Formatter | None = None,
    ignore_unknown_options: bool = False,
    allow_extra_args: bool = False,
    silent_completion: bool = False,
    with_project: bool = False,
    completion_label: str | None = None,
    manage_cli_exception: Callable[..., Any] | None = None,
) -> Callable[[Any], Any]:
    command_decorator = (
        group.command(
            name=command_name,
            context_settings=dict(
                ignore_unknown_options=ignore_unknown_options,
                allow_extra_args=allow_extra_args,
            ),
        )
        if group
        else click.command(
            command_name,
            context_settings=dict(
                ignore_unknown_options=ignore_unknown_options,
                allow_extra_args=allow_extra_args,
            ),
        )
    )
    pre_processing_kwargs: dict[str, Any] = {"with_project": with_project}
    if completion_label:
        pre_processing_kwargs["completion_label"] = completion_label
    if logger_formatter:
        pre_processing_kwargs["logger_formatter"] = logger_formatter

    exception_handler = manage_cli_exception or requires.manage_cli_exception
    return decorator_utils.composed(
        command_decorator,
        click.pass_context,
        params.log_level,
        requires.pre_processing(
            **pre_processing_kwargs,
        ),
        exception_handler(
            silent_completion=silent_completion,
        ),
    )
