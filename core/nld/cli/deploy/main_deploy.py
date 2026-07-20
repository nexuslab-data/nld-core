from typing import Any

from nld.cli import params, requires_wrapper
from nld.deploy.deploy_impact_task import DeployImpactTask
from nld.logging import StandardNldFormatter
from nld.task.task_utils import execute_task

from . import params_deploy


@requires_wrapper.nld_command(
    command_name="impact",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params_deploy.git_base
@params.nld_root_folder_path
def impact(ctx: Any, **kwargs: Any) -> Any:
    """Identify the changed and impacted assets from the repository alone.

    Diffs the repository against --git-base, maps the changed files
    to flow and structure assets, and expands the impact downstream
    through the declared dependency graph. No database connection is
    opened.
    """
    return execute_task(DeployImpactTask)
