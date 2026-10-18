from typing import Any

import click

from nld.cli import params, requires_wrapper
from nld.docs.task import DocsStateBuildTask
from nld.logging import StandardNldFormatter
from nld.task.task_utils import execute_task

from . import params_docs


@click.group(name="state", no_args_is_help=True)
@click.pass_context
def state(ctx: click.Context, /, **kwargs: Any) -> None:
    """Live state of a documented project."""


@requires_wrapper.nld_command(
    group=state,
    command_name="build",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params_docs.target_folder
@params_docs.environment
@params_docs.base_url
@params_docs.state_url
@params_docs.state_source
@params.nld_root_folder_path
def docs_state_build(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Collect the live state into a state.json beside a published site."""
    return execute_task(DocsStateBuildTask)  # type: ignore[no-any-return]
