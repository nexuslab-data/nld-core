import click

from nld.cli import params
from nld.scheduling import ExecutionFrequency

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

deps_task_name = click.option(
    "--task-name",
    "task_name",
    required=False,
    default=None,
    help="Name of the scheduled task to filter lineage on.",
)

deps_namespace = click.option(
    "--namespace",
    "namespace",
    required=False,
    default=None,
    help="Namespace of the task to filter lineage on.",
)

deps_downstream = click.option(
    "--downstream",
    is_flag=True,
    default=False,
    help="Show only downstream lineage from the specified task.",
)

deps_upstream = click.option(
    "--upstream",
    is_flag=True,
    default=False,
    help="Show only upstream lineage from the specified task.",
)

deps_override_output_folder_path = params.override_output_folder_path(
    "The file is named `scheduling_dependency_graph.json` "
    "(or `.mmd` with `--format mermaid`).",
)

frequency_filter = click.option(
    "--frequency",
    "frequency",
    required=False,
    default=None,
    type=click.Choice(
        sorted(str(value) for value in ExecutionFrequency),
        case_sensitive=False,
    ),
    help="Only report the flows declaring this intended execution frequency.",
)
