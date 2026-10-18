import click

target_folder = click.option(
    "--target",
    type=str,
    help="Folder the documentation site is written to",
    default=None,
    required=False,
)

environment = click.option(
    "--env",
    "environment",
    type=str,
    help="Environment the live state is read for",
    default=None,
    required=False,
)

host = click.option(
    "--host",
    type=str,
    help="Address the local server binds to (default: 127.0.0.1)",
    default="127.0.0.1",
    required=False,
)

port = click.option(
    "--port",
    type=int,
    help="Port the local server listens on (default: 8765)",
    default=8765,
    required=False,
)

no_state = click.option(
    "--no-state",
    "no_state",
    is_flag=True,
    default=False,
    help="Serve the project documentation only, without the live-state API",
)

no_build = click.option(
    "--no-build",
    "no_build",
    is_flag=True,
    default=False,
    help="Serve an already generated site instead of regenerating it",
)

open_browser = click.option(
    "--open",
    "open_browser",
    is_flag=True,
    default=False,
    help="Open the served site in the default browser",
)

state_ttl = click.option(
    "--state-ttl",
    "state_ttl",
    type=int,
    help="Seconds a collected live state is served from cache (default: 60)",
    default=None,
    required=False,
)

min_coverage = click.option(
    "--min-coverage",
    "min_coverage",
    type=float,
    help="Fail when the documented share of assets is under this ratio (0.0-1.0)",
    default=None,
    required=False,
)

base_url = click.option(
    "--base-url",
    "base_url",
    type=str,
    help="Public URL the site is served from, when it is not the folder root",
    default=None,
    required=False,
)

state_url = click.option(
    "--state-url",
    "state_url",
    type=str,
    help="Where the page reads its live state from (an API or a state.json)",
    default=None,
    required=False,
)

catalog_folder = click.option(
    "--catalog",
    type=str,
    help="Folder holding nld_project_catalog.yml (default: the root folder)",
    default=None,
    required=False,
)

state_source = click.option(
    "--state-source",
    "state_source",
    type=click.Choice(["none", "file", "api"], case_sensitive=False),
    help="How the published page reaches its live state (default: file when "
    "--state-url is given, otherwise none)",
    default=None,
    required=False,
)
