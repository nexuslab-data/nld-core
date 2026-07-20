import click

structure = click.option(
    "--structure",
    type=str,
    required=False,
    default=None,
    help="Name of the structure to resolve ownership for (use with --namespace).",
)

flow = click.option(
    "--flow",
    type=str,
    required=False,
    default=None,
    help="Name of the flow to resolve ownership for (use with --namespace).",
)

namespace = click.option(
    "--namespace",
    type=str,
    required=False,
    default=None,
    help="Namespace of the entity; also scopes the lookup, walking parents to root.",
)

display_format = click.option(
    "--format",
    "display_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    show_default=True,
    help=(
        "Output format. 'text' renders a concise, human-friendly summary; "
        "'json' emits the full machine-readable payload."
    ),
)
