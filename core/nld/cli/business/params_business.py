import click

from nld.cli import params

term = click.option(
    "--term",
    type=str,
    required=True,
    help="Query string to look up in the business dictionary.",
)

synonym = click.option(
    "--synonym",
    is_flag=True,
    default=False,
    help="Also match the query against each term's synonyms.",
)

related_terms = click.option(
    "--related-terms",
    "related_terms",
    is_flag=True,
    default=False,
    help="Also match the query against each term's related_terms.",
)

namespace = click.option(
    "--namespace",
    type=str,
    required=False,
    default=None,
    help="Namespace to scope the lookup; walks parents up to root.",
)

output = click.option(
    "--output",
    is_flag=True,
    default=False,
    help=(
        "Write the JSON result to a file instead of printing to stdout. "
        "When set without `--override-output-folder-path`, the file is "
        "written to a timestamped folder under `output/`."
    ),
)

override_output_folder_path = params.override_output_folder_path(
    "Implies `--output`. The file is named `business_dictionary_find.json`.",
)
