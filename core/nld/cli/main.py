from typing import Any

import click

from nld.cli.business import main_business
from nld.cli.catalog import main_catalog
from nld.cli.cli_utils import add_commands_from_modules
from nld.cli.connection import main_connection
from nld.cli.deploy import main_deploy
from nld.cli.flow import main_flow
from nld.cli.governance import main_governance
from nld.cli.project import main_project
from nld.cli.scheduling import main_scheduling
from nld.cli.sql import main_sql
from nld.cli.structure import main_structure


@click.group(no_args_is_help=True)
@click.pass_context
def cli(ctx: click.Context, /, **kwargs: Any) -> None:
    """Main command line for nld"""


@cli.group(no_args_is_help=True)
@click.pass_context
def project(ctx: click.Context, /, **kwargs: Any) -> None:
    """Main command line for project"""


add_commands_from_modules(project, main_project)


@cli.group(no_args_is_help=True)
@click.pass_context
def catalog(ctx: click.Context, /, **kwargs: Any) -> None:
    """Main command line for the nld project catalog"""


add_commands_from_modules(catalog, main_catalog)


@cli.group(no_args_is_help=True)
@click.pass_context
def connection(ctx: click.Context, /, **kwargs: Any) -> None:
    """Main command line for connection"""


add_commands_from_modules(connection, main_connection)


@cli.group(no_args_is_help=True)
@click.pass_context
def deploy(ctx: click.Context, /, **kwargs: Any) -> None:
    """Deployment-wide commands spanning flows and structures"""


add_commands_from_modules(deploy, main_deploy)


@cli.group(no_args_is_help=True)
@click.pass_context
def flow(ctx: click.Context, /, **kwargs: Any) -> None:
    """Main command line for flow"""


add_commands_from_modules(flow, main_flow)


@cli.group(no_args_is_help=True)
@click.pass_context
def sql(ctx: click.Context, /, **kwargs: Any) -> None:
    """Main command line for sql"""


add_commands_from_modules(sql, main_sql)


@cli.group(no_args_is_help=True)
@click.pass_context
def structure(ctx: click.Context, /, **kwargs: Any) -> None:
    """Main command line for structure"""


add_commands_from_modules(structure, main_structure)


@cli.group(no_args_is_help=True)
@click.pass_context
def scheduling(ctx: click.Context, /, **kwargs: Any) -> None:
    """Main command line for scheduling"""


add_commands_from_modules(scheduling, main_scheduling)


@cli.group(no_args_is_help=True)
@click.pass_context
def business(ctx: click.Context, /, **kwargs: Any) -> None:
    """Main command line for business vocabulary commands"""


add_commands_from_modules(business, main_business)


@cli.group(no_args_is_help=True)
@click.pass_context
def ownership(ctx: click.Context, /, **kwargs: Any) -> None:
    """Main command line for ownership / governance commands"""


add_commands_from_modules(ownership, main_governance)


if __name__ == "__main__":
    cli()
