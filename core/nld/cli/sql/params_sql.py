import click

flow_name = click.option(
    "--name",
    required=False,
    default=None,
    help="Name of the data flow to render",
)

flow_namespace = click.option(
    "--namespace",
    required=False,
    default=None,
    help="Namespace of the data flow",
)

in_project = click.option(
    "--in-project",
    is_flag=True,
    default=False,
    help="Write rendered SQL directly into the project flows folder",
)
