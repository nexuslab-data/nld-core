from typing import Any

from nld.cli import requires_wrapper
from nld.cli.catalog import params_catalog
from nld.logging import StandardNldFormatter
from nld.project.task import ProjectCatalogInfoTask
from nld.task.task_utils import execute_task


@requires_wrapper.nld_command(
    "info",
    logger_formatter=StandardNldFormatter(),
    with_project=False,
)
@params_catalog.root_folder_path
def info(ctx: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Display the nld project catalog: projects and their predecessor links.

    Reads ``nld_project_catalog.yml`` only — the catalogued projects themselves
    are not loaded.
    """
    return execute_task(ProjectCatalogInfoTask)  # type: ignore[no-any-return]
