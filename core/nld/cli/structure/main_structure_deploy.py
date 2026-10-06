from typing import Any

from nld.cli import params, requires_wrapper
from nld.logging import StandardNldFormatter
from nld.structure.task import StructureDeployExecuteTask
from nld.task.task_utils import execute_task

from . import params_structure


@requires_wrapper.nld_command(
    command_name="deploy",
    logger_formatter=StandardNldFormatter(),
    with_project=True,
)
@params_structure.structure_name_optional
@params_structure.deploy_namespace
@params_structure.deploy_preview
@params_structure.deploy_output
@params_structure.deploy_adopt
@params_structure.deploy_allow_drift
@params_structure.deploy_rebuild
@params.nld_root_folder_path
def deploy(ctx: Any, **kwargs: Any) -> Any:
    """Deploy the in-scope structures to match their asset definitions.

    The diff is always recomputed against the live target. Pass
    --preview to print the computed diff and DDL without applying
    anything — the command then exits with code 2 when changes are
    pending (0 when in sync) and --output writes the change entries
    as JSON. A target modified outside nld refuses the deploy by
    default; --adopt records the live schema as a flagged baseline
    first, --allow-drift deploys against it anyway, and --rebuild
    recreates the structures from the assets.

    A failing structure is recorded and the run continues with the
    independent rest (structures whose claimed name a failed rename
    target never freed are skipped); the run then ends with a
    partial/failed status and a summary error.
    """
    result = execute_task(StructureDeployExecuteTask)
    if kwargs.get("preview") and isinstance(result, list) and result:
        # Distinct exit code so CI drift gates can branch on
        # "changes pending" without parsing output.
        ctx.exit(2)
    return result
