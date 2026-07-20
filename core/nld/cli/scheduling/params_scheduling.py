import click

environment = click.option(
    "--env",
    "environment",
    required=False,
    default=None,
    help=(
        "Environment to resolve scheduling for. Falls back to the "
        "NLD__ENVIRONMENT variable, then environments.default."
    ),
)

output_format = click.option(
    "--format",
    "output_format",
    type=click.Choice(
        ["json", "mermaid"],
        case_sensitive=False,
    ),
    default="json",
    help="Output format for the scheduling dependency graph.",
)

deps_flow_name = click.option(
    "--flow-name",
    "flow_name",
    required=False,
    default=None,
    help="Name of the scheduled flow to filter lineage on.",
)

deps_namespace = click.option(
    "--namespace",
    "namespace",
    required=False,
    default=None,
    help="Namespace of the flow to filter lineage on.",
)

deps_downstream = click.option(
    "--downstream",
    is_flag=True,
    default=False,
    help="Show only downstream lineage from the specified flow.",
)

deps_upstream = click.option(
    "--upstream",
    is_flag=True,
    default=False,
    help="Show only upstream lineage from the specified flow.",
)
