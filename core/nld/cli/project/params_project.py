import click

entity_type = click.option(
    "--entity-type",
    type=str,
    envvar=None,
    help="Entity Type",
    default=None,
    required=True,
)

namespace = click.option(
    "--namespace",
    type=str,
    required=False,
    default=None,
    help="Namespace",
)
