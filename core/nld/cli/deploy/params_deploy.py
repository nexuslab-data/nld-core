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

unlock_target = click.option(
    "--target",
    "target",
    multiple=True,
    help=(
        "Deploy target whose lock to release, as <connection>:<schema> "
        "(repeatable). Without it, the current locks are listed and "
        "nothing is released."
    ),
)
