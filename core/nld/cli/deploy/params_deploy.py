import click

git_base = click.option(
    "--git-base",
    "git_base",
    required=True,
    help=(
        "Git ref to diff the repository against (e.g. origin/main). "
        "The analysis is repository-only: no database is touched."
    ),
)
