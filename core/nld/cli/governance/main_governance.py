from typing import Any

import click

from nld.cli import params, requires_wrapper
from nld.cli.governance import params_governance
from nld.governance.task import OwnershipListTask, OwnershipResolveTask
from nld.logging import StandardNldFormatter
from nld.task.task_utils import execute_task


@requires_wrapper.nld_command(
    command_name="resolve",
    logger_formatter=StandardNldFormatter(),
    silent_completion=True,
    with_project=True,
)
@params.nld_root_folder_path
@params_governance.structure
@params_governance.flow
@params_governance.namespace
@params_governance.display_format
def resolve(ctx: click.Context, **kwargs: Any) -> bool:
    """Resolve the effective owner(s) of a structure, a flow, or a namespace, as JSON.

    For a structure, emits the pair of data owner(s) (nearest structure-owner
    declaration, else the union of upstream sources reached by lineage) and
    technical owner(s) (the owner of its producing flow). For a flow, emits the
    technical owner. With only `--namespace` (no `--structure`/`--flow`), emits
    the pair for every structure under that namespace and its descendants.

    Renders a human-friendly summary by default; pass `--format json` for the
    full machine-readable payload.

    Examples:

        nld ownership resolve --flow r_fr_postal_code --namespace fr_geography

        nld ownership resolve --structure refined_opendata_fr_department \\
            --namespace fr_geography

        nld ownership resolve --namespace fr_geography

        nld ownership resolve --namespace fr_geography --format json
    """
    return execute_task(OwnershipResolveTask)  # type: ignore[no-any-return]


@requires_wrapper.nld_command(
    command_name="list",
    logger_formatter=StandardNldFormatter(),
    silent_completion=True,
    with_project=True,
)
@params.nld_root_folder_path
@params_governance.namespace
def list_owners(ctx: click.Context, **kwargs: Any) -> bool:
    """List the ownership declarations visible from a namespace.

    Shows the resolved set (nearest namespace wins) of structure owners (data
    responsibility) and flow owners (technical responsibility).

    Examples:

        nld ownership list

        nld ownership list --namespace fr_geography
    """
    return execute_task(OwnershipListTask)  # type: ignore[no-any-return]
