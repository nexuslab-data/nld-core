import dataclasses
import uuid
from typing import Any, ClassVar, cast

from nld.connector.base.connector import SQLDataConnector
from nld.deploy import (
    DeploymentLockManager,
    DeploymentScopeManager,
    DeploymentScopeRow,
)
from nld.deploy.change_file_loader import (
    get_flow_renames,
    get_reloads,
    group_backfill_defaults_by_structure,
    group_field_renames_by_structure,
    group_structure_renames_by_source,
    group_structure_renames_by_target,
)
from nld.deploy.change_file_models import (
    BackfillDefaultDirective,
    RenameFieldDirective,
    RenameStructureDirective,
    reload_outcome_key,
    rename_flow_outcome_key,
)
from nld.deploy.change_log_manager import (
    DeploymentChangeLogManager,
)
from nld.flow.deploy.flow_change_set import FlowChangeEntry, FlowChangeSet
from nld.flow.deploy.flow_deploy_diff import FlowDeployAction
from nld.flow.deploy.flow_deploy_metadata_manager import FlowDeployMetadataManager
from nld.flow.deploy.flow_deploy_metadata_models import (
    FlowDeployHistoryRow,
    FlowDeploymentFlowChangeRow,
    FlowDeploymentRow,
    FlowDeploymentStructureChangeRow,
    FlowDeployMetadataRow,
)
from nld.flow.task.data_flow_executor import DataFlowExecutor
from nld.parameters.execution_params_def import ExecutionParameterDefinition
from nld.pydantic import build_entity_key
from nld.service import EntityTypeNames
from nld.structure.deploy import StructureMetadataBackendManager
from nld.structure.deploy.deploy_target_factory import StructureDeployTargetFactory
from nld.structure.deploy.structure_change import (
    StructureChangeEntry,
    StructureDeployAction,
)
from nld.task.base import StandardTask
from nld.utils import resolve_variables
from nld.utils.datetime_util import get_current_datetime

FLOW_DEPLOY_COMMAND = "flow deploy"


class FlowDeployResult:
    """Aggregated result of a deploy execution."""

    def __init__(
        self,
        deployment_id: str = "",
    ) -> None:
        self.deployed: list[FlowChangeEntry] = []
        self.deployment_id = deployment_id
        self.failed: dict[str, str] = {}
        self.skipped: dict[str, str] = {}
        self.structures_deployed: list[str] = []
        self.structures_failed: dict[str, str] = {}
        self.structures_skipped: dict[str, str] = {}

    @property
    def total(self) -> int:
        return len(self.deployed) + len(self.failed) + len(self.skipped)

    @property
    def succeeded_count(self) -> int:
        return len(self.deployed)

    @property
    def failed_count(self) -> int:
        return len(self.failed)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @property
    def structures_total(self) -> int:
        return (
            len(self.structures_deployed)
            + len(self.structures_failed)
            + len(self.structures_skipped)
        )

    @property
    def structures_succeeded_count(self) -> int:
        return len(self.structures_deployed)

    @property
    def structures_failed_count(self) -> int:
        return len(self.structures_failed)

    @property
    def structures_skipped_count(self) -> int:
        return len(self.structures_skipped)


@dataclasses.dataclass
class _StructureRoundState:
    """Shared bookkeeping of one change-set execution round.

    One instance per ``_execute_deployment`` call, aliasing the same
    collections the flow loop reads, so the three structure-deploy
    sites share one code path (``_deploy_one_structure``).
    """

    deployment_id: str
    result: FlowDeployResult
    deployed_structures: set[str]
    skipped_structure_keys: set[str]
    directive_outcomes: dict[str, str]
    view_flows_to_execute: list[str]
    renames_by_structure: dict[str, Any]
    structure_renames_by_target: dict[str, Any]
    structure_renames_by_source: dict[str, Any]
    backfill_defaults_by_structure: dict[str, Any]


class FlowDeployExecutor(StandardTask):
    """Applies an in-memory change set computed by the planner.

    The executor iterates flow entries in topological order, applies
    structure DDL interleaved before the flows that target each
    structure, records deployment metadata, and cascade-skips
    dependents on failure. It never executes flows: deployment only
    changes shape and records state — repopulating data is the
    separate reload concern.

    The executor is intentionally **planning-agnostic**: it never calls
    the planner. Producing the change set is the orchestrator's
    responsibility (see ``FlowDeployTask``).
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = []
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        change_set: FlowChangeSet,
        adopt: bool = False,
        allow_drift: bool = False,
        deploy_target_factory: StructureDeployTargetFactory | None = None,
        metadata_manager: FlowDeployMetadataManager | None = None,
        rebuild: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._adopt = adopt
        self._allow_drift = allow_drift
        self._change_set = change_set
        self._metadata_manager = metadata_manager
        self._rebuild = rebuild

        metadata_backend_connector_name = (
            self.execution_context.project.metadata_backend_connector
        )
        if metadata_backend_connector_name is None:
            raise ValueError(
                "metadata_backend_connector must be set in the project "
                "configuration to use FlowDeployExecutor.",
            )

        self._metadata_backend_connector: SQLDataConnector[Any] = cast(
            SQLDataConnector[Any],
            self.execution_context.get_data_connector(
                metadata_backend_connector_name,
                open_connection=True,
            ),
        )
        if self._metadata_manager is None:
            self._metadata_manager = FlowDeployMetadataManager(
                connector=self._metadata_backend_connector,
            )

        metadata_schema = self._metadata_backend_connector.get_active_schema()
        if metadata_schema is None:
            raise ValueError(
                "metadata_backend_connector must have a schema configured. "
                "Set 'schema_name' on the connection credentials.",
            )
        self._metadata_schema = metadata_schema
        self._structure_metadata_manager = StructureMetadataBackendManager(
            metadata_connector=self._metadata_backend_connector,
        )
        self._deploy_target_factory = deploy_target_factory
        self.execution_context.load_entities(
            entity_types=[EntityTypeNames.DATA_FLOW_DEFINITION]
        )

    @property
    def deploy_target_factory(self) -> StructureDeployTargetFactory:
        """The run's shared per-(connection, schema) manager factory.

        The orchestrator passes the planner's factory so applying
        reuses the managers (and prefetched snapshots) planning
        already built instead of recomputing everything per structure.
        Built lazily on first use when none was passed.
        """
        if self._deploy_target_factory is None:
            self._deploy_target_factory = StructureDeployTargetFactory(
                connector_resolver=self._resolve_sql_connector,
                metadata_connector=self._metadata_backend_connector,
                metadata_schema=self._metadata_schema,
                variables=resolve_variables(
                    project_variables=self.execution_context.project.variables,
                ),
            )
        return self._deploy_target_factory

    def _resolve_sql_connector(
        self,
        connection_name: str,
    ) -> SQLDataConnector[Any]:
        """Open (or reuse) a named SQL connector from the execution context."""
        return cast(
            SQLDataConnector[Any],
            self.execution_context.get_data_connector(
                connection_name,
                open_connection=True,
            ),
        )

    def run(
        self,
        **kwargs: Any,
    ) -> FlowDeployResult:
        """Apply the configured change set, holding its targets' deploy lock.

        A deploy changing a target another deploy is changing refuses
        before recording anything; deploys of distinct targets run
        concurrently.
        """
        deployment_id = str(uuid.uuid4())
        lock_manager = DeploymentLockManager(
            connector=self._metadata_backend_connector,
        )
        with lock_manager.hold(
            metadata_schema=self._metadata_schema,
            lock_keys=self._change_set.scope.lock_keys,
            holder_id=deployment_id,
            command=FLOW_DEPLOY_COMMAND,
            scope=self._change_set.scope.describe(),
        ):
            return self._execute_deployment(
                change_set=self._change_set,
                deployment_id=deployment_id,
            )

    # ------------------------------------------------------------------
    # Change-set execution
    # ------------------------------------------------------------------

    def _execute_deployment(
        self,
        change_set: FlowChangeSet,
        deployment_id: str,
    ) -> FlowDeployResult:
        """Execute a single change set."""
        result = FlowDeployResult(deployment_id=deployment_id)
        skipped_flow_names: set[str] = set()

        # Insert deployment record at the start
        if self._metadata_manager is not None and self._metadata_schema is not None:
            self._metadata_manager.ensure_metadata_tables(
                metadata_schema=self._metadata_schema,
            )
            self._structure_metadata_manager.ensure_metadata_tables(
                metadata_schema=self._metadata_schema,
            )
            deployment_row = FlowDeploymentRow(
                deployment_id=deployment_id,
                changeset_id=change_set.changeset_id,
                started_at=get_current_datetime(),
                flows_total=len(change_set.flows),
            )
            self._metadata_manager.insert_deployment(
                metadata_schema=self._metadata_schema,
                record=deployment_row,
            )
            DeploymentScopeManager(
                connector=self._metadata_backend_connector,
            ).record(
                metadata_schema=self._metadata_schema,
                row=DeploymentScopeRow.build(
                    deployment_id=deployment_id,
                    command=FLOW_DEPLOY_COMMAND,
                    recorded_at=get_current_datetime(),
                    requested_namespace=change_set.scope.namespace,
                    requested_name=change_set.scope.flow_name,
                    unit_namespaces=change_set.scope.namespaces,
                    deploy_groups=change_set.scope.groups,
                    lock_keys=change_set.scope.lock_keys,
                ),
            )

        # --- Build lookup maps from links for interleaved execution
        flow_target_structures = self._build_flow_target_structure_map(
            change_set=change_set,
        )
        structure_entries_by_key = self._build_structure_entry_map(
            change_set=change_set,
        )
        deployed_structures: set[str] = set()
        skipped_structure_keys: set[str] = set()
        renames_by_structure = group_field_renames_by_structure(
            pending_change_files=change_set.pending_change_files,
        )
        structure_renames_by_target = group_structure_renames_by_target(
            pending_change_files=change_set.pending_change_files,
        )
        structure_renames_by_source = group_structure_renames_by_source(
            pending_change_files=change_set.pending_change_files,
        )
        backfill_defaults_by_structure = group_backfill_defaults_by_structure(
            pending_change_files=change_set.pending_change_files,
        )
        directive_outcomes: dict[str, str] = {}
        view_flows_to_execute: list[str] = []
        round_state = _StructureRoundState(
            deployment_id=deployment_id,
            result=result,
            deployed_structures=deployed_structures,
            skipped_structure_keys=skipped_structure_keys,
            directive_outcomes=directive_outcomes,
            view_flows_to_execute=view_flows_to_execute,
            renames_by_structure=renames_by_structure,
            structure_renames_by_target=structure_renames_by_target,
            structure_renames_by_source=structure_renames_by_source,
            backfill_defaults_by_structure=backfill_defaults_by_structure,
        )

        # --- Interleaved structure + flow deployment phase
        try:
            # Entries whose planning already failed deploy nothing:
            # they are recorded as failures up front so the flows
            # targeting them cascade-skip and the run ends partial or
            # failed instead of silently dropping the structure.
            for failed_entry in change_set.structures:
                if failed_entry.action != StructureDeployAction.FAILED:
                    continue
                structure_key = self._build_structure_key(
                    namespace=failed_entry.namespace,
                    structure_name=failed_entry.structure_name,
                )
                error_msg = failed_entry.planning_error or "planning failed"
                self.log_error(
                    f"Structure '{structure_key}' cannot deploy: {error_msg}",
                )
                skipped_structure_keys.add(structure_key)
                result.structures_failed[structure_key] = error_msg

            # Declared flow renames move their backend state row to
            # the new name before any flow records state: a new flow
            # reclaiming the old name must mint a fresh identity, not
            # inherit (or be wiped with) the renamed flow's row.
            for flow_rename in get_flow_renames(
                pending_change_files=change_set.pending_change_files,
            ):
                outcome_key = rename_flow_outcome_key(directive=flow_rename)
                directive_outcomes[outcome_key] = self._apply_flow_rename(
                    from_full_name=flow_rename.from_name,
                    to_full_name=flow_rename.to,
                )
                self.log_info(f"Applied {outcome_key}")

            # Rename-target structures deploy first: the declared
            # rename frees its old table name before any structure
            # reclaiming that name deploys.
            for rename_target_entry in change_set.structures:
                structure_key = self._build_structure_key(
                    namespace=rename_target_entry.namespace,
                    structure_name=rename_target_entry.structure_name,
                )
                if structure_key not in structure_renames_by_target:
                    continue
                if structure_key in skipped_structure_keys:
                    continue
                self._deploy_one_structure(
                    structure_entry=rename_target_entry,
                    structure_key=structure_key,
                    round_state=round_state,
                    include_claiming_renames=False,
                )

            for entry in change_set.flows:
                flow_key = self._build_flow_key(
                    namespace=entry.namespace,
                    flow_name=entry.flow_name,
                )

                # Skip unchanged or removed flows
                if entry.action in (
                    FlowDeployAction.UNCHANGED,
                    FlowDeployAction.REMOVED,
                ):
                    result.skipped[flow_key] = f"{entry.action} (no action needed)"
                    self._record_flow_change(
                        deployment_id=deployment_id,
                        entry=entry,
                        status="skipped",
                    )
                    continue

                # Skip flows whose predecessors failed
                if flow_key in skipped_flow_names:
                    result.skipped[flow_key] = "predecessor failed"
                    self._record_flow_change(
                        deployment_id=deployment_id,
                        entry=entry,
                        status="skipped",
                        error_message="predecessor failed",
                    )
                    continue

                # Deploy target structures before recording this flow
                structure_failed = False
                for structure_key in flow_target_structures.get(flow_key, set()):
                    if structure_key in deployed_structures:
                        continue
                    if structure_key in skipped_structure_keys:
                        structure_failed = True
                        continue
                    structure_entry = structure_entries_by_key.get(structure_key)
                    if structure_entry is None:
                        continue
                    if not self._deploy_one_structure(
                        structure_entry=structure_entry,
                        structure_key=structure_key,
                        round_state=round_state,
                    ):
                        structure_failed = True

                if structure_failed:
                    for sk in flow_target_structures.get(flow_key, set()):
                        if (
                            sk in skipped_structure_keys
                            and sk not in result.structures_failed
                        ):
                            result.structures_skipped[sk] = (
                                "predecessor structure failed"
                            )
                    result.skipped[flow_key] = "target structure deployment failed"
                    self._record_flow_change(
                        deployment_id=deployment_id,
                        entry=entry,
                        status="skipped",
                        error_message="target structure deployment failed",
                    )
                    dependents = self._get_dependent_flow_keys(
                        failed_entry=entry,
                        change_set=change_set,
                    )
                    skipped_flow_names.update(dependents)
                    continue

                try:
                    flow_history_id = self._record_flow_deployment(
                        entry=entry,
                        result=result,
                        deployment_id=deployment_id,
                    )
                    self._record_flow_change(
                        deployment_id=deployment_id,
                        entry=entry,
                        status="success",
                        flow_history_id=flow_history_id,
                    )
                except Exception as exc:
                    error_msg = str(exc)
                    result.failed[flow_key] = error_msg
                    self.log_error(f"Flow '{flow_key}' deployment failed: {error_msg}")

                    self._record_flow_change(
                        deployment_id=deployment_id,
                        entry=entry,
                        status="failed",
                        error_message=error_msg,
                    )

                    # Cascade-skip dependents
                    dependents = self._get_dependent_flow_keys(
                        failed_entry=entry,
                        change_set=change_set,
                    )
                    skipped_flow_names.update(dependents)

            # Deploy structures not reached by the flow loop
            for structure_entry in change_set.structures:
                structure_key = self._build_structure_key(
                    namespace=structure_entry.namespace,
                    structure_name=structure_entry.structure_name,
                )
                if structure_key in deployed_structures:
                    continue
                if structure_key in skipped_structure_keys:
                    continue
                self._deploy_one_structure(
                    structure_entry=structure_entry,
                    structure_key=structure_key,
                    round_state=round_state,
                )

            self._execute_view_flows(
                view_flows_to_execute=view_flows_to_execute,
            )

            self._apply_reload_directives(
                change_set=change_set,
                deployment_id=deployment_id,
                directive_outcomes=directive_outcomes,
            )

            self._record_applied_change_files(
                change_set=change_set,
                deployment_id=deployment_id,
                directive_outcomes=directive_outcomes,
            )
        finally:
            # Always update deployment record, even when an unexpected
            # error interrupts the loop.
            if self._metadata_manager is not None and self._metadata_schema is not None:
                status = self._compute_deployment_status(result=result)
                self._metadata_manager.update_deployment_status(
                    metadata_schema=self._metadata_schema,
                    deployment_id=deployment_id,
                    status=status,
                    completed_at=get_current_datetime(),
                    flows_in_error=result.failed_count,
                    flows_in_success=result.succeeded_count,
                    flows_skipped=result.skipped_count,
                    structures_in_error=result.structures_failed_count,
                    structures_in_success=result.structures_succeeded_count,
                    structures_skipped=result.structures_skipped_count,
                    structures_total=result.structures_total,
                )

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_flow_deployment(
        self,
        entry: FlowChangeEntry,
        result: FlowDeployResult,
        deployment_id: str,
    ) -> str | None:
        """Record the deployment of one flow entry.

        Returns:
            The flow history deployment_id, or None if metadata
            recording is disabled.
        """
        flow_key = self._build_flow_key(
            namespace=entry.namespace,
            flow_name=entry.flow_name,
        )

        flow_history_id: str | None = None
        if self._metadata_manager is not None and self._metadata_schema is not None:
            flow_history_id = self._record_deployment_metadata(
                entry=entry,
                run_deployment_id=deployment_id,
            )

        result.deployed.append(entry)
        self.log_info(f"Flow '{flow_key}' deployed successfully")

        return flow_history_id

    @staticmethod
    def _claiming_renames_for(
        structure_key: str,
        structure_renames_by_source: dict[str, list[RenameStructureDirective]],
    ) -> list[RenameStructureDirective]:
        """Return the pending renames moving another asset off this name."""
        return [
            directive
            for directive in structure_renames_by_source.get(structure_key, [])
            if directive.to != structure_key
        ]

    def _deploy_one_structure(
        self,
        structure_entry: StructureChangeEntry,
        structure_key: str,
        round_state: _StructureRoundState,
        include_claiming_renames: bool = True,
    ) -> bool:
        """Deploy one structure entry with the round's shared bookkeeping.

        Returns True on success; on failure the error is recorded,
        the key is marked skipped for the rest of the run and False
        returns. Rename targets pass ``include_claiming_renames=False``
        — a rename target is never the claiming side of its own
        directive.
        """
        try:
            structure_dep_id, rename_outcomes = self._execute_structure_from_entry(
                structure_entry=structure_entry,
                pending_field_renames=round_state.renames_by_structure.get(
                    structure_key,
                    [],
                ),
                pending_structure_renames=(
                    round_state.structure_renames_by_target.get(structure_key, [])
                ),
                pending_claiming_renames=(
                    self._claiming_renames_for(
                        structure_key=structure_key,
                        structure_renames_by_source=(
                            round_state.structure_renames_by_source
                        ),
                    )
                    if include_claiming_renames
                    else None
                ),
                pending_backfill_defaults=(
                    round_state.backfill_defaults_by_structure.get(structure_key, [])
                ),
            )
            round_state.directive_outcomes.update(rename_outcomes)
            round_state.deployed_structures.add(structure_key)
            round_state.result.structures_deployed.append(structure_key)
            if structure_dep_id is not None:
                self._record_structure_change(
                    deployment_id=round_state.deployment_id,
                    structure_deployment_id=structure_dep_id,
                )
                self._collect_view_flows(
                    structure_entry=structure_entry,
                    view_flows_to_execute=round_state.view_flows_to_execute,
                )
            return True
        except Exception as exc:
            error_msg = str(exc)
            self.log_error(
                f"Structure '{structure_entry.structure_name}' "
                f"deployment failed: {error_msg}"
            )
            round_state.skipped_structure_keys.add(structure_key)
            round_state.result.structures_failed[structure_key] = error_msg
            return False

    def _execute_structure_from_entry(
        self,
        structure_entry: StructureChangeEntry,
        pending_field_renames: list[RenameFieldDirective] | None = None,
        pending_structure_renames: list[RenameStructureDirective] | None = None,
        pending_claiming_renames: list[RenameStructureDirective] | None = None,
        pending_backfill_defaults: list[BackfillDefaultDirective] | None = None,
    ) -> tuple[str | None, dict[str, str]]:
        """Deploy a structure from its change-set entry.

        Returns the structure deployment_id (None when nothing was
        deployed) and the resolved directive outcomes (renames and
        backfill defaults). A structure with no schema change
        (``action == NONE``) still deploys when a backfill_default
        directive is pending against it — it is a one-shot data fill,
        not a schema change, so it does not participate in the
        schema-change action classification.
        """
        if (
            structure_entry.action == StructureDeployAction.NONE
            and not pending_backfill_defaults
            and not self._adopt
        ):
            return None, {}

        structure_config = self.execution_context.project.structure_namespace_config
        mapping = structure_config.get_mapping(
            namespace=structure_entry.namespace,
        )

        registry = self.execution_context.entity_registry
        namespaced_structure = registry.get_structure(
            entity_key=structure_entry.structure_name,
            namespace=structure_entry.namespace,
        )

        deploy_manager = self.deploy_target_factory.get_manager(
            connection_name=mapping.default_connection_name,
            schema_name=mapping.schema_name,
        )

        deploy_result = deploy_manager.deploy(
            namespaced_structure=namespaced_structure,
            adopt=self._adopt,
            allow_dependent_view_drops=True,
            allow_drift=self._allow_drift,
            pending_field_renames=pending_field_renames,
            pending_structure_renames=pending_structure_renames,
            pending_claiming_renames=pending_claiming_renames,
            pending_backfill_defaults=pending_backfill_defaults,
            rebuild=self._rebuild,
        )
        if deploy_result.deployed:
            # Applied DDL logs at info: after an incident the
            # default-verbosity log must show what actually ran, not
            # only what the preview promised.
            for stmt in deploy_result.statements:
                self.log_info(f"Executed DDL: {stmt.sql}")

        structure_key = self._build_structure_key(
            namespace=structure_entry.namespace,
            structure_name=structure_entry.structure_name,
        )
        self.log_info(
            f"Structure '{structure_key}' deployed successfully "
            f"[{structure_entry.action}]",
        )

        return deploy_result.deployment_id, deploy_result.rename_outcomes

    @staticmethod
    def _collect_view_flows(
        structure_entry: StructureChangeEntry,
        view_flows_to_execute: list[str],
    ) -> None:
        """Queue the entry's view flows, once, preserving dependency order."""
        for flow_full_name in structure_entry.view_flows_to_execute:
            if flow_full_name not in view_flows_to_execute:
                view_flows_to_execute.append(flow_full_name)

    def _execute_view_flows(
        self,
        view_flows_to_execute: list[str],
    ) -> None:
        """Force-execute the VIEW flows whose views were dropped.

        Dependent views are dropped before the table DDL; re-running
        their flows (shallowest first) recreates them against the new
        schema. This is the one place deployment executes flows — a
        view is shape, not data, and only its own flow can rebuild it.
        """
        if not view_flows_to_execute:
            return
        registry = self.execution_context.entity_registry
        for flow_full_name in view_flows_to_execute:
            namespace, _, flow_name = flow_full_name.rpartition(".")
            namespaced_flow = registry.get_data_flow_definition(
                entity_key=flow_name,
                namespace=namespace or None,
            )
            flow_executor = DataFlowExecutor(
                namespaced_data_flow_definition=namespaced_flow,
            )
            data_flow_task = flow_executor.init_data_flow_task(
                connections_should_be_opened=True,
            )
            flow_executor.execute_data_flow_task(data_flow_task=data_flow_task)
            self.log_info(
                f"Recreated dependent view via flow '{flow_full_name}'",
            )

    def _apply_reload_directives(
        self,
        change_set: FlowChangeSet,
        deployment_id: str,
        directive_outcomes: dict[str, str],
    ) -> None:
        """Apply the flow-scoped pending directives.

        Directive failures propagate and fail the deployment; the
        change file then stays pending. Flow renames are not applied
        here: their state-row move runs before the flow loop.
        backfill_default is structure-scoped and resolved during the
        structure deploy phase, not here.
        """
        for reload_directive in get_reloads(
            pending_change_files=change_set.pending_change_files,
        ):
            outcome_key = reload_outcome_key(directive=reload_directive)
            directive_outcomes[outcome_key] = self._apply_reload(
                flow_full_name=reload_directive.flow,
                deployment_id=deployment_id,
            )
            self.log_info(
                f"Applied {outcome_key}: {directive_outcomes[outcome_key]}",
            )

    def _apply_flow_rename(
        self,
        from_full_name: str,
        to_full_name: str,
    ) -> str:
        """Move the backend state row of a renamed flow to its new name.

        Runs before the flow loop: the renamed flow then finds its
        identity (uid) under the new name, and a new flow reclaiming
        the old name mints a fresh identity instead of inheriting —
        or being wiped with — the renamed flow's row.
        """
        if self._metadata_manager is None or self._metadata_schema is None:
            return "no-op (metadata recording disabled)"

        from_namespace, _, from_flow_name = from_full_name.rpartition(".")
        to_namespace, _, to_flow_name = to_full_name.rpartition(".")
        from_namespace = from_namespace or "."
        to_namespace = to_namespace or "."

        old_row = self._metadata_manager.read_state_row(
            metadata_schema=self._metadata_schema,
            flow_name=from_flow_name,
            namespace=from_namespace,
        )
        if old_row is None:
            return "no-op (no backend state row under the old name)"

        new_row = self._metadata_manager.read_state_row(
            metadata_schema=self._metadata_schema,
            flow_name=to_flow_name,
            namespace=to_namespace,
        )
        self._metadata_manager.delete_state_row(
            metadata_schema=self._metadata_schema,
            namespace=from_namespace,
            flow_name=from_flow_name,
        )
        if new_row is not None:
            return "no-op (already effective — old state row removed)"

        moved_row = old_row.model_copy(
            update={
                "flow_name": to_flow_name,
                "namespace": to_namespace,
            },
        )
        self._metadata_manager.upsert_current_state(
            metadata_schema=self._metadata_schema,
            record=moved_row,
        )
        return "renamed (backend state row moved to the new name)"

    def _apply_reload(
        self,
        flow_full_name: str,
        deployment_id: str,
    ) -> str:
        """Record the reload intent as a deploy-created planned state.

        A full-coverage PLANNED processing state is persisted with
        requestor ``deploy:<deployment_id>``; the next flow execution
        consumes it as TRUST and marks it COMPLETED. Deploy itself
        never runs the flow. Flows whose every run is already a full
        refresh need nothing; backends without planned-state support
        degrade to an explicit warning.
        """
        registry = self.execution_context.entity_registry
        namespace, _, flow_name = flow_full_name.rpartition(".")
        namespaced_flow = registry.get_data_flow_definition(
            entity_key=flow_name,
            namespace=namespace or None,
        )

        flow_executor = DataFlowExecutor(
            namespaced_data_flow_definition=namespaced_flow,
        )
        # The reload intent is a FULL refresh by definition, so the
        # incremental parameters are forced to full coverage.
        data_flow_task = flow_executor.init_data_flow_task(
            connections_should_be_opened=True,
            extra_init_params={"full": True},
        )

        definition = data_flow_task.incremental_definition
        if not definition.tracks_state:
            return "no-op (every run is already a full refresh)"

        supports_planned_state = (
            definition.supports_planned_state
            and data_flow_task.state_manager.backend_supports_planned_state
        )
        if not supports_planned_state:
            self.log_warn(
                f"Reload requested for flow '{flow_full_name}' but its "
                "state backend cannot hold a planned state — run "
                f"`nld flow execute {flow_full_name} --full` manually "
                "to refresh the history.",
            )
            return "warning (planned state unsupported — manual full run required)"

        data_flow_task.compute_incremental_state(persist_to_backend=False)
        processing_state = data_flow_task.state_manager.processing_state
        if processing_state is None:
            self.log_warn(
                f"Reload requested for flow '{flow_full_name}' but no "
                "processing state could be computed — run "
                f"`nld flow execute {flow_full_name} --full` manually.",
            )
            return "warning (no processing state computed — manual full run required)"

        plan_state_uid = data_flow_task.exec_uuid
        data_flow_task.state_manager.save_planned_processing_state(
            processing_flow_state=processing_state,
            plan_state_uid=plan_state_uid,
            computed_at=get_current_datetime(),
            requestor=f"deploy:{deployment_id}",
        )
        return f"planned full refresh (plan {plan_state_uid})"

    def _record_applied_change_files(
        self,
        change_set: FlowChangeSet,
        deployment_id: str,
        directive_outcomes: dict[str, str],
    ) -> None:
        """Record the resolved directives and completed change files.

        Each directive resolved in this run is recorded, so no later
        deploy applies it again; a change file joins the applied-log
        once every one of its directives is recorded — a scoped deploy
        leaves the directives outside its scope pending for the deploy
        of their own scope.
        """
        if self._metadata_schema is None:
            return
        if not change_set.pending_change_files:
            return

        change_log_manager = DeploymentChangeLogManager(
            connector=self._metadata_backend_connector,
        )
        change_log_manager.ensure_table(
            metadata_schema=self._metadata_schema,
        )

        change_log_manager.record_applied_directives(
            metadata_schema=self._metadata_schema,
            pending_change_files=change_set.pending_change_files,
            directive_outcomes=directive_outcomes,
            deployment_id=deployment_id,
        )

    def _record_deployment_metadata(
        self,
        entry: FlowChangeEntry,
        run_deployment_id: str,
    ) -> str | None:
        """Write metadata and history records for a deployed flow.

        Returns:
            The flow history deployment_id, or None if metadata
            recording is disabled.
        """
        if self._metadata_manager is None or self._metadata_schema is None:
            return None

        deployment_id = str(uuid.uuid4())
        now = get_current_datetime()

        uid, previous_deployment_id = self._resolve_flow_identity(
            entry=entry,
        )

        # Compute hashes from the current flow definition
        entities_root = self.execution_context.project.entities_root_folder_path
        entity_layout = self.execution_context.project.entity_layout
        additional_flow_task_types = (
            self.execution_context.project.flow_config.additional_flow_task_types
        )
        additional_task_paths = (
            self.execution_context.project.flows_python_additional_paths
        )
        registry = self.execution_context.entity_registry

        namespaced_flow = registry.get_data_flow_definition(
            entity_key=entry.flow_name,
            namespace=entry.namespace,
        )

        from nld.flow.deploy.flow_definition_hash import (
            build_flow_yaml_snapshot_json,
            compute_flow_definition_hash,
            compute_flow_python_hash,
            compute_flow_sql_hash,
            compute_flow_yaml_hash,
        )
        from nld.structure.deploy import compute_structure_hash

        flow_def = namespaced_flow.model
        yaml_hash = compute_flow_yaml_hash(flow_definition=flow_def)
        sql_hash = compute_flow_sql_hash(
            entities_root_folder_path=entities_root,
            namespace=entry.namespace,
            flow_name=entry.flow_name,
            entity_layout=entity_layout,
        )
        python_hash = compute_flow_python_hash(
            flow_definition=flow_def,
            namespace=entry.namespace,
            entity_layout=entity_layout,
            additional_task_paths=additional_task_paths,
            additional_flow_task_types=additional_flow_task_types,
        )
        definition_hash = compute_flow_definition_hash(
            flow_definition=flow_def,
            entities_root_folder_path=entities_root,
            namespace=entry.namespace,
            entity_layout=entity_layout,
            additional_task_paths=additional_task_paths,
            additional_flow_task_types=additional_flow_task_types,
        )

        # Compute target structure hash
        target_structure_hash = None
        if flow_def.target_structure is not None:
            try:
                resolved_structure = flow_def.resolve_target_structure()
                target_structure_hash = compute_structure_hash(
                    structure=resolved_structure,
                )
            except Exception:
                pass

        # Compute predecessor hashes
        predecessor_hashes: dict[str, str] | None = None
        if flow_def.predecessors:
            pred_hashes: dict[str, str] = {}
            for _pred_name, predecessor in flow_def.predecessors.items():
                try:
                    resolved = predecessor.full_path.resolve(
                        entity_type=EntityTypeNames.STRUCTURE,
                    )
                    pred_hashes[str(predecessor.full_path)] = compute_structure_hash(
                        structure=resolved,
                    )
                except Exception:
                    pass
            if pred_hashes:
                predecessor_hashes = pred_hashes

        # Compute flow YAML snapshot
        flow_yaml_snapshot = build_flow_yaml_snapshot_json(
            flow_definition=flow_def,
        )

        metadata_row = FlowDeployMetadataRow(
            namespace=entry.namespace,
            flow_name=entry.flow_name,
            deployment_id=deployment_id,
            uid=uid,
            deployed_at=now,
            flow_definition_hash=definition_hash,
            flow_yaml_hash=yaml_hash,
            flow_sql_hash=sql_hash,
            flow_python_hash=python_hash,
            flow_yaml_snapshot=flow_yaml_snapshot,
            last_deployment_id=run_deployment_id,
            predecessor_hashes=predecessor_hashes,
            target_structure_hash=target_structure_hash,
        )

        history_row = FlowDeployHistoryRow(
            deployment_id=deployment_id,
            uid=uid,
            namespace=entry.namespace,
            flow_name=entry.flow_name,
            deployed_at=now,
            flow_definition_hash=definition_hash,
            flow_yaml_hash=yaml_hash,
            flow_sql_hash=sql_hash,
            flow_python_hash=python_hash,
            flow_yaml_snapshot=flow_yaml_snapshot,
            target_structure_hash=target_structure_hash,
            diff_action=str(entry.action),
            run_deployment_id=run_deployment_id,
            predecessor_hashes=predecessor_hashes,
            previous_deployment_id=previous_deployment_id,
        )

        self._metadata_manager.upsert_current_state(
            metadata_schema=self._metadata_schema,
            record=metadata_row,
        )
        self._metadata_manager.write_history_record(
            metadata_schema=self._metadata_schema,
            record=history_row,
        )

        return deployment_id

    def _resolve_flow_identity(
        self,
        entry: FlowChangeEntry,
    ) -> tuple[str, str | None]:
        """Resolve the stable uid and previous deployment id of a flow.

        A declared flow rename carries the identity of the old-name
        record forward; with no previous record a fresh uid is minted.
        """
        assert self._metadata_manager is not None
        assert self._metadata_schema is not None

        previous_row = self._metadata_manager.read_state_row(
            metadata_schema=self._metadata_schema,
            flow_name=entry.flow_name,
            namespace=entry.namespace,
        )
        if previous_row is not None:
            return previous_row.uid, previous_row.deployment_id

        flow_key = self._build_flow_key(
            namespace=entry.namespace,
            flow_name=entry.flow_name,
        )
        for rename in get_flow_renames(
            pending_change_files=self._change_set.pending_change_files,
        ):
            if rename.to != flow_key:
                continue
            old_namespace, _, old_name = rename.from_name.rpartition(".")
            old_row = self._metadata_manager.read_state_row(
                metadata_schema=self._metadata_schema,
                flow_name=old_name,
                namespace=old_namespace or ".",
            )
            if old_row is not None:
                return old_row.uid, old_row.deployment_id

        return str(uuid.uuid4()), None

    def _record_flow_change(
        self,
        deployment_id: str,
        entry: FlowChangeEntry,
        status: str,
        error_message: str | None = None,
        flow_history_id: str | None = None,
    ) -> None:
        """Record a flow change in the deployment flow change table."""
        if self._metadata_manager is None or self._metadata_schema is None:
            return

        record = FlowDeploymentFlowChangeRow(
            deployment_id=deployment_id,
            flow_name=entry.flow_name,
            namespace=entry.namespace,
            status=status,
            changed_at=get_current_datetime(),
            error_message=error_message,
            flow_history_id=flow_history_id,
        )
        self._metadata_manager.insert_flow_change(
            metadata_schema=self._metadata_schema,
            record=record,
        )

    def _record_structure_change(
        self,
        deployment_id: str,
        structure_deployment_id: str,
    ) -> None:
        """Link a flow deployment to a structure deployment."""
        if self._metadata_manager is None or self._metadata_schema is None:
            return

        record = FlowDeploymentStructureChangeRow(
            deployment_id=deployment_id,
            structure_deployment_id=structure_deployment_id,
            changed_at=get_current_datetime(),
        )
        self._metadata_manager.insert_structure_change(
            metadata_schema=self._metadata_schema,
            record=record,
        )

    def _compute_deployment_status(
        self,
        result: FlowDeployResult,
    ) -> str:
        """Compute the overall deployment status from results.

        Structure failures count: a run that silently dropped or
        failed a structure must not report success even when every
        flow entry recorded cleanly.
        """
        failed = result.failed_count + result.structures_failed_count
        succeeded = result.succeeded_count + result.structures_succeeded_count
        if failed > 0 and succeeded > 0:
            return "partial"
        if failed > 0:
            return "failed"
        return "success"

    def _get_dependent_flow_keys(
        self,
        failed_entry: FlowChangeEntry,
        change_set: FlowChangeSet,
    ) -> set[str]:
        """Find all flow keys that transitively depend on the failed flow.

        Uses the change set's dependency links to traverse the graph
        and identify flows that should be skipped when a predecessor
        fails.
        """
        failed_key = self._build_flow_key(
            namespace=failed_entry.namespace,
            flow_name=failed_entry.flow_name,
        )

        # Build adjacency map from links
        adjacency: dict[str, set[str]] = {}
        for link in change_set.links:
            source_key = f"{link.source_type}.{link.source_id}"
            target_key = f"{link.target_type}.{link.target_id}"
            if source_key not in adjacency:
                adjacency[source_key] = set()
            adjacency[source_key].add(target_key)

        # BFS from the failed flow to find all transitive dependents
        failed_node = f"flow.{failed_key}"
        dependents: set[str] = set()
        frontier = {failed_node}

        while frontier:
            current = frontier.pop()
            for downstream in adjacency.get(current, set()):
                if downstream not in dependents and downstream != failed_node:
                    dependents.add(downstream)
                    frontier.add(downstream)

        # Extract flow keys from dependent node IDs
        flow_keys: set[str] = set()
        for dep in dependents:
            if dep.startswith("flow."):
                flow_keys.add(dep[len("flow.") :])

        return flow_keys

    def _build_flow_key(
        self,
        namespace: str,
        flow_name: str,
    ) -> str:
        """Build a unique key from namespace and flow name."""
        return build_entity_key(namespace=namespace, entity_name=flow_name)

    def _build_structure_key(
        self,
        namespace: str,
        structure_name: str,
    ) -> str:
        """Build a unique key from namespace and structure name."""
        return build_entity_key(namespace=namespace, entity_name=structure_name)

    def _build_flow_target_structure_map(
        self,
        change_set: FlowChangeSet,
    ) -> dict[str, set[str]]:
        """Build a mapping from flow keys to their target structure keys.

        Uses the change-set links to identify which structures each
        flow writes to, so structures can be deployed right before
        the flow that targets them.
        """
        flow_targets: dict[str, set[str]] = {}
        for link in change_set.links:
            if link.source_type == "flow" and link.target_type == "structure":
                flow_targets.setdefault(link.source_id, set()).add(
                    link.target_id,
                )
        return flow_targets

    def _build_structure_entry_map(
        self,
        change_set: FlowChangeSet,
    ) -> dict[str, StructureChangeEntry]:
        """Build a mapping from structure keys to their change-set entries.

        Keys use the ``namespace.structure_name`` format which
        matches the link ``target_id`` produced by the planner.
        """
        entries: dict[str, StructureChangeEntry] = {}
        for structure_entry in change_set.structures:
            key = self._build_structure_key(
                namespace=structure_entry.namespace,
                structure_name=structure_entry.structure_name,
            )
            entries[key] = structure_entry
        return entries
