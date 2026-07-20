import click

root_folder_path = click.option(
    "--root-folder-path",
    type=str,
    default=".",
    show_default=True,
    required=False,
    help="Folder holding nld_project_catalog.yml (default: current directory)",
)
