import click

from nld.cli import params
from nld.utils import decorator_utils

structure_name = click.option(
    "--name",
    required=True,
    help="Name of the structure",
)

structure_namespace = click.option(
    "--namespace",
    required=False,
    default=None,
    help="Namespace of the structure",
)

renderer = click.option(
    "--renderer",
    required=True,
    help="Renderer folder name inside sql_templates",
)

specific_sql_renderer_params = decorator_utils.composed(
    params.structure,
    renderer,
    params.output_folder_name_not_required,
)

adapter = click.option(
    "--adapter",
    required=True,
    help="Structure adapter name inside the adapter folder",
)

adapter_name = click.option(
    "--adapter-name",
    required=True,
    help="Structure adapter name inside the adapter folder",
)

source_structure_name = click.option(
    "--structure-name",
    required=True,
    help="Name of the source structure",
)

source_structure_namespace = click.option(
    "--structure-namespace",
    required=False,
    default=None,
    help="Namespace of the source structure",
)

output_csv = click.option(
    "--output-csv",
    help="Output the csv file",
    is_flag=True,
    envvar=None,
    default=False,
    required=False,
)


plan_only = click.option(
    "--plan-only",
    is_flag=True,
    default=False,
    help="Only generate DDL without executing",
)

structure_name_optional = click.option(
    "--name",
    required=False,
    default=None,
    help="Name of the structure",
)


from_plan = click.option(
    "--from-plan",
    is_flag=True,
    default=False,
    help="Execute from previously generated deployment manifests",
)

manifest_path = click.option(
    "--manifest-path",
    required=False,
    default=None,
    type=click.Path(exists=True),
    help="Path to a specific deploy manifest YAML file. "
    "If omitted, all pending manifests in .deployments/structures/ are executed.",
)


specific_structure_build_params = decorator_utils.composed(
    adapter,
    params.structure,
    params.output_folder_name_not_required,
    params.output_inside_project,
    output_csv,
)


specific_structure_convert_to_yaml_params = decorator_utils.composed(
    params.structure, params.output_folder_name_not_required
)
