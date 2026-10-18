from typing import Any

import click

from nld.cli import params, requires_wrapper
from nld.docs.task import DocsCatalogBuildTask
from nld.logging import StandardNldFormatter
from nld.task.task_utils import execute_task

from . import params_docs


@click.group(name="catalog", no_args_is_help=True)
@click.pass_context
def catalog(ctx: click.Context, /, **kwargs: Any) -> None:
    """Documentation of every project of a platform catalog."""


@requires_wrapper.nld_command(
    group=catalog,
    command_name="build",
    logger_formatter=StandardNldFormatter(),
)
@params_docs.catalog_folder
@params_docs.target_folder
@params_docs.environment
@params_docs.base_url
@params.nld_root_folder_path
def docs_catalog_build(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Generate one site per catalogued project, plus an index."""
    return execute_task(DocsCatalogBuildTask)  # type: ignore[no-any-return]
