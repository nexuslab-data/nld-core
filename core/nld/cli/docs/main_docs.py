from typing import Any

import click

from nld.cli import params, requires_wrapper
from nld.docs.task import (
    DocsBuildTask,
    DocsCheckTask,
    DocsDeployTask,
    DocsServeTask,
)
from nld.logging import StandardNldFormatter
from nld.task.task_utils import execute_task

from . import params_docs
from .catalog_docs import catalog as catalog_group
from .state_docs import state as state_group


@click.group(name="docs", no_args_is_help=True)
@click.pass_context
def docs(ctx: click.Context, /, **kwargs: Any) -> None:
    """Generate and serve the documentation UI of the whole nld project."""


@requires_wrapper.nld_command(
    group=docs,
    command_name="build",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params_docs.target_folder
@params_docs.environment
@params_docs.base_url
@params_docs.state_url
@params_docs.state_source
@params_docs.catalog_folder
@params.nld_root_folder_path
def docs_build(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Generate the static documentation site from the project assets."""
    return execute_task(DocsBuildTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command(
    group=docs,
    command_name="deploy",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params_docs.target_folder
@params_docs.environment
@params_docs.base_url
@params_docs.state_url
@params_docs.state_source
@params_docs.catalog_folder
@params.nld_root_folder_path
def docs_deploy(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Generate the self-contained deployable documentation application."""
    return execute_task(DocsDeployTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command(
    group=docs,
    command_name="serve",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params_docs.target_folder
@params_docs.environment
@params_docs.host
@params_docs.port
@params_docs.no_state
@params_docs.no_build
@params_docs.open_browser
@params_docs.state_ttl
@params.nld_root_folder_path
def docs_serve(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Serve the documentation locally, with the live-state API enabled."""
    return execute_task(DocsServeTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command(
    group=docs,
    command_name="check",
    logger_formatter=StandardNldFormatter(),
    silent_completion=True,
    with_project=True,
)
@params_docs.environment
@params_docs.min_coverage
@params_docs.catalog_folder
@params.nld_root_folder_path
def docs_check(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Check documentation coverage and cross-references of the project assets."""
    result = execute_task(DocsCheckTask)
    if result is False:
        # A non-zero exit is what lets CI gate on broken references
        # or on the --min-coverage threshold without parsing output.
        ctx.exit(1)
    return result  # type: ignore[no-any-return]


docs.add_command(catalog_group)
docs.add_command(state_group)
