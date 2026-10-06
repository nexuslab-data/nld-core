import click

from nld.cli import params
from nld.cli.utils.mutually_exclusive_option import MutuallyExclusiveOption
from nld.utils import decorator_utils

deps_downstream = click.option(
    "--downstream",
    is_flag=True,
    default=False,
    help="Show only downstream lineage from the specified node.",
)

deps_flow_name = click.option(
    "--flow-name",
    "flow_name",
    required=False,
    default=None,
    help="Name of the flow to filter lineage on.",
)

deps_namespace = click.option(
    "--namespace",
    required=False,
    default=None,
    help="Namespace of the target flow or structure.",
)

deps_structure_name = click.option(
    "--structure-name",
    "structure_name",
    required=False,
    default=None,
    help="Name of the structure to filter lineage on.",
)

deps_upstream = click.option(
    "--upstream",
    is_flag=True,
    default=False,
    help="Show only upstream lineage from the specified node.",
)

deps_override_output_folder_path = params.override_output_folder_path(
    "The file is named `flow_dependency_graph.json` "
    "(or `.mmd` with `--format mermaid`).",
)

deploy_downstream = click.option(
    "--downstream",
    is_flag=True,
    default=False,
    help="Include downstream flows in the deployment scope",
)

deploy_upstream = click.option(
    "--upstream",
    is_flag=True,
    default=False,
    help="Include upstream flows in the deployment scope",
)

deploy_preview = click.option(
    "--preview",
    is_flag=True,
    default=False,
    help=(
        "Compute and print the change set (including the structure "
        "DDL) against the live target without applying anything. "
        "Exits with code 2 when changes are pending, 0 when the "
        "target is in sync."
    ),
)

deploy_output = click.option(
    "--output",
    "output",
    type=str,
    default=None,
    help=(
        "With --preview, also write the computed change set as JSON "
        "to this file path — for CI gates and PR bots that must not "
        "scrape log lines."
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

flow_name = click.option(
    "--name",
    required=True,
    help="Name of the data flow",
)

flow_name_optional = click.option(
    "--name",
    required=False,
    default=None,
    help="Name of the data flow",
)

flow_namespace = click.option(
    "--namespace",
    required=False,
    default=None,
    help="Namespace of the data flow",
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

full = click.option(
    "--full",
    is_flag=True,
    default=False,
    help="Force FULL loading strategy.",
)

output_format = click.option(
    "--format",
    "output_format",
    type=click.Choice(
        ["json", "mermaid"],
        case_sensitive=False,
    ),
    default="json",
    help="Output format for the dependency graph.",
)

render = click.option(
    "--render",
    is_flag=True,
    default=False,
    help=(
        "Render the SQL query from flow metadata before executing."
        " Only works for SQL tasks."
    ),
)

with_delta = click.option(
    "--with-delta",
    is_flag=True,
    default=False,
    help=(
        "Force DELTA-based loading strategy."
        " Combined with backfill parameters, uses BACKFILL_DELTA."
    ),
)

with_views = click.option(
    "--with-views",
    is_flag=True,
    default=False,
    help="Include VIEW flows in execution. By default, views are skipped.",
)

planned_state_policy = click.option(
    "--planned-state-policy",
    "planned_state_policy",
    type=click.Choice(
        ["auto", "trust", "recompute", "strict"],
        case_sensitive=False,
    ),
    default="auto",
    show_default=True,
    help=(
        "How to react to a PLANNED state precomputed by "
        "`nld flow state incremental compute --persist`. "
        "'auto' (default) adopts the plan when it is still consistent with "
        "the latest incremental state, recomputing otherwise; 'recompute' "
        "ignores any plan; 'trust' adopts the plan as-is without validation; "
        "'strict' fails when no plan exists or the plan is stale."
    ),
)

state_output = click.option(
    "--output",
    is_flag=True,
    default=False,
    help=(
        "Write the JSON result to a file instead of printing to stdout. "
        "Without --override-output-folder-path the file is written to a "
        "timestamped folder under output/."
    ),
)

state_override_output_folder_path = params.override_output_folder_path(
    "Implies --output. The file name is fixed per command.",
)

state_display_format = click.option(
    "--format",
    "display_format",
    type=click.Choice(
        ["text", "json"],
        case_sensitive=False,
    ),
    default="text",
    show_default=True,
    help=(
        "Output format when printing to stdout. 'text' renders a "
        "concise, human-friendly summary; 'json' emits the full "
        "machine-readable payload. File output via --output / "
        "--override-output-folder-path always writes JSON."
    ),
)

state_file_output_params = decorator_utils.composed(
    state_output,
    state_override_output_folder_path,
    state_display_format,
)

state_history_limit = click.option(
    "--limit",
    type=int,
    required=False,
    default=None,
    help=("Maximum number of executions to return (newest first). Default: no limit."),
)

state_steps_flow_uid = click.option(
    "--flow-uid",
    "flow_uid",
    type=str,
    required=False,
    default=None,
    cls=MutuallyExclusiveOption,
    mutually_exclusive=["latest"],
    required_group=True,
    help="Execution UID to load steps from.",
)

state_steps_latest = click.option(
    "--latest",
    is_flag=True,
    default=False,
    cls=MutuallyExclusiveOption,
    mutually_exclusive=["flow_uid"],
    required_group=True,
    help="Load steps from the latest execution.",
)

state_processing_only = click.option(
    "--processing-only",
    "processing_only",
    is_flag=True,
    default=False,
    help=(
        "Show only the last run's processing state instead of the current "
        "authoritative state."
    ),
)

state_compute_only = click.option(
    "--state-compute-only",
    "state_compute_only",
    is_flag=True,
    default=False,
    help=(
        "Compute and persist the incremental processing state without "
        "executing the flow. Equivalent to 'nld flow state incremental "
        "compute --persist'. Requires --name and is incompatible with "
        "--downstream / --upstream."
    ),
)

state_compute_persist = click.option(
    "--persist",
    "persist",
    is_flag=True,
    default=False,
    help=(
        "Persist the computed processing state to the state backend as "
        "a PLANNED plan, cancelling any prior PLANNED plan for this flow."
    ),
)

state_compute_requestor = click.option(
    "--requestor",
    "requestor",
    type=str,
    required=False,
    default=None,
    help=(
        "Identifier of the user / system requesting the compute. "
        "Recorded on the persisted plan when --persist is set. "
        "Defaults to the current OS user."
    ),
)

state_compute_source_request_authorized = click.option(
    "--source-request-authorized",
    "source_request_authorized",
    is_flag=True,
    default=False,
    help=(
        "Confirm in advance that the source-side queries triggered by "
        "``retrieve_source_state`` are authorized. When omitted and the "
        "incremental definition declares ``requires_source_state_retrieval``, "
        "the CLI prompts for confirmation interactively."
    ),
)

deploy_interactive = click.option(
    "--interactive/--no-interactive",
    "interactive",
    default=True,
    help=(
        "Prompt the user to confirm before applying any DDL. "
        "--no-interactive skips the prompt — useful in CI pipelines."
    ),
)

list_incremental_type = click.option(
    "--incremental-type",
    "incremental_type",
    required=False,
    default=None,
    help="Keep only the data flows using this incremental type.",
)
