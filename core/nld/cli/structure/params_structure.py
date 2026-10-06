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

deploy_namespace = click.option(
    "--namespace",
    required=False,
    default=None,
    help=(
        "Deploy one namespace on its own, when nld_project.yml declares "
        "it with 'deploy: {unit: true}' or a deploy group: the namespace "
        "and its descendants mapped to the same connection and schema. "
        "Descendants mapped elsewhere are left out, a group member "
        "brings every member, and a target outside the scope refuses "
        "the deploy. With --name, it only locates the asset. Without "
        "it, the whole project deploys."
    ),
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


deploy_preview = click.option(
    "--preview",
    is_flag=True,
    default=False,
    help=(
        "Compute and print the diff and DDL against the live target "
        "without applying anything. Exits with code 2 when changes "
        "are pending, 0 when the target is in sync."
    ),
)

deploy_output = click.option(
    "--output",
    "output",
    type=str,
    default=None,
    help=(
        "With --preview, also write the computed change entries as "
        "JSON to this file path — for CI gates and PR bots that must "
        "not scrape log lines."
    ),
)

deploy_adopt = click.option(
    "--adopt",
    is_flag=True,
    default=False,
    help=(
        "On drift: record the live schema as a flagged state-refresh "
        "baseline, then deploy against it."
    ),
)

deploy_allow_drift = click.option(
    "--allow-drift",
    "allow_drift",
    is_flag=True,
    default=False,
    help=(
        "On drift: deploy against the live schema anyway, without "
        "recording a new baseline."
    ),
)

deploy_rebuild = click.option(
    "--rebuild",
    is_flag=True,
    default=False,
    help=(
        "Recreate the in-scope structures from the assets, ignoring "
        "both the recorded and the live state (destructive)."
    ),
)

structure_name_optional = click.option(
    "--name",
    required=False,
    default=None,
    help="Name of the structure",
)

structure_model_name = click.option(
    "--name",
    required=True,
    help="Name of the structure model",
)

structure_model_name_optional = click.option(
    "--name",
    required=False,
    default=None,
    help="Name of the structure model (validate all when omitted)",
)

structure_model_info_output = click.option(
    "--output",
    "output",
    type=click.Choice(["diagram", "detailed"]),
    default="diagram",
    show_default=True,
    help="Display format: 'diagram' (visual links) or 'detailed' (full text).",
)

structure_audit_name = click.option(
    "--name",
    required=True,
    help="Name of the structure audit",
)

structure_audit_name_optional = click.option(
    "--name",
    required=False,
    default=None,
    help="Name of the structure audit (validate all when omitted)",
)

structure_audit_run_connection = click.option(
    "--connection",
    "connection",
    required=False,
    default=None,
    help=("Connection name to query (defaults to the structure namespace mapping)."),
)

structure_audit_run_sample = click.option(
    "--sample",
    "sample",
    required=False,
    default=None,
    type=int,
    help="Audit a random sample of at most N rows instead of the full table.",
)

structure_audit_run_environment = click.option(
    "--environment",
    "environment",
    required=False,
    default=None,
    help="Target environment label recorded in the audit (default: prd).",
)

structure_audit_run_force = click.option(
    "--force",
    "force",
    is_flag=True,
    default=False,
    help="Overwrite an existing audit YAML instead of skipping.",
)

structure_audit_run_new_version = click.option(
    "--new-version",
    "new_version",
    is_flag=True,
    default=False,
    help=(
        "Write a timestamped audit alongside the canonical one "
        "(<audit-name>.<YYYYMMDDThhmmss>.yml) instead of overwriting or skipping."
    ),
)

structure_audit_render_override_output_folder_path = params.override_output_folder_path(
    "The file is the rendered markdown report.",
)

structure_audit_render_stdout = click.option(
    "--stdout",
    "stdout",
    is_flag=True,
    default=False,
    help="Print the rendered markdown to stdout instead of writing a file.",
)

display_format = click.option(
    "--format",
    "display_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    show_default=True,
    help=(
        "Output format. 'text' renders a concise, human-friendly summary; "
        "'json' emits the full machine-readable payload."
    ),
)

property_filter = click.option(
    "--property",
    "property",
    multiple=True,
    help="Filter by property as key=value (repeatable; matches are ANDed).",
)

tag_filter = click.option(
    "--tag",
    "tag",
    multiple=True,
    help="Filter by tag (repeatable; matches are ANDed).",
)

generate_check = click.option(
    "--check",
    is_flag=True,
    default=False,
    help=(
        "Write nothing: print the diff of every generated structure that a "
        "generation would change, and exit non-zero when one is stale."
    ),
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
