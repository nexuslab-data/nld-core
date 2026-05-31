import click

database = click.option(
    "--database",
    type=str,
    required=False,
    default=None,
    help="Database name (validates against connection, uses connection DB if omitted)",
)

schema = click.option(
    "--schema",
    type=str,
    required=False,
    default=None,
    help="Filter by schema name",
)

object_name = click.option(
    "--object",
    type=str,
    required=False,
    default=None,
    help="Filter by table/view name",
)
