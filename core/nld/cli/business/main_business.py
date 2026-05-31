from typing import Any

import click

from nld.business.task import BusinessDictionaryFindTask
from nld.cli import params, requires_wrapper
from nld.cli.business import params_business
from nld.task.task_utils import execute_task


@click.group(name="dict", no_args_is_help=True)
@click.pass_context
def dictionary(ctx: click.Context, /, **kwargs: Any) -> None:
    """Business dictionary commands."""


@requires_wrapper.nld_command(
    group=dictionary,
    command_name="find",
    with_project=True,
)
@params.nld_root_folder_path
@params_business.term
@params_business.synonym
@params_business.related_terms
@params_business.namespace
@params_business.output
@params_business.override_output_folder_path
def find(ctx: click.Context, **kwargs: Any) -> bool:
    """Look up business dictionary terms and emit the results as JSON.

    By default the query is matched against each term's canonical name.
    Add `--synonym` to also match against synonyms, and `--related-terms`
    to also match against related_terms. The flags compose.

    Examples:

        nld business dict find --term customer

        nld business dict find --term counterparty --synonym --namespace finance

        nld business dict find --term customer --synonym --output

        nld business dict find --term customer --synonym --related-terms \\
            --override-output-folder-path ./out
    """
    return execute_task(BusinessDictionaryFindTask)  # type: ignore[no-any-return]
