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

query = click.option(
    "--query",
    type=str,
    required=False,
    default=None,
    help="Inline SELECT query to execute",
)

query_file = click.option(
    "--query-file",
    type=str,
    required=False,
    default=None,
    help="Path to a .sql file holding the SELECT query",
)

output_file = click.option(
    "--output-file",
    type=str,
    required=False,
    default=None,
    help="Destination CSV file path (defaults to query_result.csv)",
)

delimiter = click.option(
    "--delimiter",
    type=str,
    required=False,
    default=None,
    help="CSV field delimiter (defaults to a comma)",
)

no_header = click.option(
    "--no-header",
    is_flag=True,
    default=False,
    required=False,
    help="Omit the header row from the CSV file",
)
