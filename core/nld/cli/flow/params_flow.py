import click

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

plan_only = click.option(
    "--plan-only",
    is_flag=True,
    default=False,
    help=(
        "Generate the deployment plan without executing it. In the "
        "default in-memory mode of `deploy execute`, this writes a "
        "manifest YAML to .deployments/flows/ and exits — equivalent "
        "to `nld flow deploy plan`. Mutually exclusive with --from-plan "
        "(and with --manifest-path, which implies --from-plan)."
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

full = click.option(
    "--full",
    is_flag=True,
    default=False,
    help="Force FULL loading strategy.",
)

interactive = click.option(
    "--interactive/--no-interactive",
    default=True,
    help="Enable interactive prompts for rename candidates",
)

no_backfill = click.option(
    "--no-backfill",
    is_flag=True,
    default=False,
    help=(
        "Suppress backfill for all flows. With --from-plan, overrides "
        "the manifest's backfill_strategy entries. In the default "
        "in-memory mode of `deploy execute`, no-backfill is already "
        "applied by default — pass --with-backfill to opt in."
    ),
)

with_backfill = click.option(
    "--with-backfill",
    is_flag=True,
    default=False,
    help=(
        "Run backfills as part of the default in-memory `deploy execute` "
        "mode. By default, no-backfill is applied to avoid rewriting "
        "historical data on a one-shot deploy. Mutually exclusive with "
        "--from-plan and --no-backfill."
    ),
)

manifest_path = click.option(
    "--manifest-path",
    required=False,
    default=None,
    type=click.Path(exists=True),
    help="Path to a specific deploy manifest YAML file. "
    "If omitted, all pending manifests in .deployments/flows/ are executed.",
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

planned_state_strategy = click.option(
    "--planned-state-strategy",
    "planned_state_strategy",
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

from_plan = click.option(
    "--from-plan",
    is_flag=True,
    default=False,
    help=(
        "Apply pre-generated manifests instead of planning in memory. "
        "Loads either the file passed to --manifest-path, or all pending "
        "manifests in .deployments/flows/ (sorted). Implied when "
        "--manifest-path is provided."
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

state_override_output_folder_path = click.option(
    "--override-output-folder-path",
    "override_output_folder_path",
    type=click.Path(file_okay=False, writable=True),
    required=False,
    default=None,
    help=(
        "Folder to write the JSON result into; implies --output. The "
        "file name is fixed per command."
    ),
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

state_include_post_processing = click.option(
    "--include-post-processing",
    "include_post_processing",
    is_flag=True,
    default=False,
    help=(
        "Also include the authoritative post-processing state in the "
        "payload (returned as an object with both states)."
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

deploy_execute_interactive = click.option(
    "--interactive/--no-interactive",
    "interactive",
    default=True,
    help=(
        "When the in-memory plan mode is used (the default), prompt the "
        "user to confirm before applying any DDL or backfill. "
        "--no-interactive skips the prompt — useful in CI pipelines. "
        "Has no effect when --from-plan is set."
    ),
)
