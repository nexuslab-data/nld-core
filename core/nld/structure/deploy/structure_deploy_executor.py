from __future__ import annotations

import json
import uuid
from contextlib import AbstractContextManager, nullcontext
from typing import Any, ClassVar, cast

from nld.connector.base.connector import SQLDataConnector
from nld.deploy import (
    DeploymentLockManager,
    DeploymentScopeManager,
    DeploymentScopeRow,
    NamespaceDeployScope,
    resolve_lock_keys,
    resolve_namespace_deploy_scope,
    scope_pending_change_files,
)
from nld.deploy.change_file_loader import (
    group_backfill_defaults_by_structure,
    group_field_renames_by_structure,
    group_structure_renames_by_source,
    group_structure_renames_by_target,
    resolve_pending_change_files,
    validate_backfill_default_targets,
)
from nld.deploy.change_file_models import (
    BackfillDefaultDirective,
    PendingChangeFile,
    backfill_default_outcome_key,
)
from nld.deploy.change_log_manager import (
    DeploymentChangeLogManager,
)
from nld.exceptions import NldRuntimeException
from nld.parameters.execution_params_def import ExecutionParameterDefinition
from nld.pydantic.namespace import build_entity_key
from nld.service import EntityTypeNames
from nld.structure.deploy.deploy_target_factory import StructureDeployTargetFactory
from nld.structure.deploy.structure_change import (
    StructureChangeEntry,
    StructureDeployAction,
)
from nld.structure.deploy.structure_deploy_manager import StructureDeployManager
from nld.structure.deploy.structure_diff import DiffAction, StructureDiff
from nld.structure.deploy.structure_metadata_backend_manager import (
    StructureMetadataBackendManager,
)
from nld.structure.deploy.structure_metadata_models import StructureDeployRunRow
from nld.structure.structure.structure import NamespacedStructure, Structure
from nld.task.base import StandardTask
from nld.utils import resolve_variables
from nld.utils.datetime_util import get_current_datetime

STRUCTURE_DEPLOY_COMMAND = "structure deploy"


class StructureDeployExecutor(StandardTask):
    """Deploys the in-scope structures to match their asset definitions.

    The diff is always recomputed against the live target at run
    time. With ``preview=True`` the computed diff and DDL are printed
    and nothing is executed or recorded.

    A change needing dependent views dropped is refused (only ``nld
    flow deploy`` can recreate them by re-executing their VIEW
    flows), except with ``adopt=True``: reconciling a live database
    must not be blocked by its own views, so they are dropped without
    re-execution and the next flow deploy recreates them.

    Failure contract (shared with ``nld flow deploy``): a failing
    structure is recorded and the run continues with the independent
    rest; structures depending on the failure (a name a failed rename
    target never freed) are skipped; the run ends with a
    partial/failed status — recorded on the run-level record — and a
    summary error.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(
            name="adopt",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="allow_drift",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="name",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="namespace",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="output",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="preview",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="rebuild",
            mandatory=False,
        ),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        adopt: bool = False,
        allow_drift: bool = False,
        name: str | None = None,
        namespace: str | None = None,
        output: str | None = None,
        preview: bool = False,
        rebuild: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._adopt = adopt
        self._allow_drift = allow_drift
        self._name = name
        self._namespace = namespace
        self._output = output
        self._preview = preview
        self._rebuild = rebuild
        self._deploy_target_factory: StructureDeployTargetFactory | None = None
        self._change_log: tuple[DeploymentChangeLogManager, str] | None = None
        self.execution_context.load_entities(entity_types=[EntityTypeNames.STRUCTURE])

    def run(self, **kwargs: Any) -> bool | list[StructureChangeEntry]:
        """Deploy or preview the in-scope structures.

        A preview returns the structured change entries (optionally
        written as JSON via ``output``); an apply returns True or
        raises with a partial/failed summary.
        """
        resolved_namespace = self._resolve_namespace(
            namespace=self._namespace,
            structure_name=self._name,
        )
        # With --name the namespace only locates the structure: a single
        # structure deploys without the namespace being declared deployable.
        deploy_scope = (
            None
            if self._name is not None
            else self._resolve_deploy_scope(namespace=resolved_namespace)
        )
        deployment_id = str(uuid.uuid4())
        with self._hold_deploy_lock(
            deploy_scope=deploy_scope,
            deployment_id=deployment_id,
        ):
            return self._deploy_structures(
                resolved_namespace=resolved_namespace,
                deploy_scope=deploy_scope,
                deployment_id=deployment_id,
            )

    def _deploy_structures(
        self,
        resolved_namespace: str | None,
        deploy_scope: NamespaceDeployScope | None,
        deployment_id: str,
    ) -> bool | list[StructureChangeEntry]:
        """Deploy or preview the structures of the resolved scope."""
        structures_to_deploy = self._load_structures_to_deploy(
            namespace=resolved_namespace,
            structure_name=self._name,
            deploy_scope=deploy_scope,
        )

        pending_change_files = self._load_pending_change_files(
            deploy_scope=deploy_scope,
        )
        renames_by_structure = group_field_renames_by_structure(
            pending_change_files=pending_change_files,
        )
        structure_renames_by_target = group_structure_renames_by_target(
            pending_change_files=pending_change_files,
        )
        structure_renames_by_source = group_structure_renames_by_source(
            pending_change_files=pending_change_files,
        )
        backfill_defaults_by_structure = group_backfill_defaults_by_structure(
            pending_change_files=pending_change_files,
        )
        self._validate_backfill_default_targets(
            backfill_defaults_by_structure=backfill_defaults_by_structure,
        )
        directive_outcomes: dict[str, str] = {}

        # Rename targets deploy first: a declared rename frees its old
        # name before any new structure reclaiming that name deploys.
        ordered_structures = self._order_rename_targets_first(
            structures_to_deploy=structures_to_deploy,
            structure_renames_by_target=structure_renames_by_target,
        )

        started_at = get_current_datetime()
        failed: dict[str, str] = {}
        skipped: dict[str, str] = {}
        succeeded_count = 0
        preview_entries: list[StructureChangeEntry] = []
        if not self._preview:
            self._start_run_record(
                deployment_id=deployment_id,
                started_at=started_at,
                structures_total=len(ordered_structures),
                deploy_scope=deploy_scope,
            )

        for namespaced_structure in ordered_structures:
            structure_full_name = self._build_structure_full_name(
                namespaced_structure=namespaced_structure,
            )
            pending_field_renames = renames_by_structure.get(
                structure_full_name,
                [],
            )
            pending_structure_renames = structure_renames_by_target.get(
                structure_full_name,
                [],
            )
            pending_claiming_renames = [
                directive
                for directive in structure_renames_by_source.get(
                    structure_full_name,
                    [],
                )
                if directive.to != structure_full_name
            ]
            pending_backfill_defaults = backfill_defaults_by_structure.get(
                structure_full_name,
                [],
            )
            if self._preview:
                preview_entry = self._preview_structure(
                    deploy_manager=self._get_deploy_manager(
                        namespace=namespaced_structure.namespace,
                    ),
                    namespaced_structure=namespaced_structure,
                    pending_field_renames=pending_field_renames,
                    pending_structure_renames=pending_structure_renames,
                    pending_claiming_renames=pending_claiming_renames,
                    pending_backfill_defaults=pending_backfill_defaults,
                )
                if preview_entry is not None:
                    preview_entries.append(preview_entry)
                continue

            # A structure reclaiming a name that a failed rename
            # target never freed must not deploy — it would ALTER a
            # table it does not own.
            blocking_targets = [
                directive.to
                for directive in pending_claiming_renames
                if directive.to in failed
            ]
            if blocking_targets:
                reason = f"rename target failed: {', '.join(blocking_targets)}"
                skipped[structure_full_name] = reason
                self.log_error(
                    f"Skipping structure '{structure_full_name}': {reason}",
                )
                continue

            try:
                # The mapping (connection, schema) is resolved per
                # structure, inside the failure boundary: a structure
                # whose target cannot be reached fails on its own
                # instead of aborting the run with its record open.
                deploy_manager = self._get_deploy_manager(
                    namespace=namespaced_structure.namespace,
                )
                result = deploy_manager.deploy(
                    namespaced_structure=namespaced_structure,
                    adopt=self._adopt,
                    allow_dependent_view_drops=self._adopt,
                    allow_drift=self._allow_drift,
                    pending_field_renames=pending_field_renames,
                    pending_structure_renames=pending_structure_renames,
                    pending_claiming_renames=pending_claiming_renames,
                    pending_backfill_defaults=pending_backfill_defaults,
                    rebuild=self._rebuild,
                )
            except Exception as ex:
                # Per-structure failure semantics, like nld flow
                # deploy: record, continue with the independent rest,
                # end the run partial/failed.
                self.log_error(
                    f"Error deploying structure '{structure_full_name}': {ex}",
                )
                failed[structure_full_name] = str(ex)
                continue

            succeeded_count += 1
            directive_outcomes.update(result.rename_outcomes)

            if result.deployed:
                summary = self._build_deploy_summary(
                    structure=namespaced_structure.model,
                    diff=result.diff,
                )
                self.log_info(summary)
            else:
                self.log_info(
                    f"Structure '{namespaced_structure.model.name}' is in sync"
                )

        if self._preview:
            if preview_entries:
                self.log_info(
                    f"[PREVIEW] {len(preview_entries)} of "
                    f"{len(ordered_structures)} structure(s) with pending "
                    "changes",
                )
            else:
                self.log_info("[PREVIEW] No changes detected — empty change set")
            self._write_preview_output(preview_entries=preview_entries)
            # The structured change entries are the preview's return
            # value: the CLI exits with a distinct code when any are
            # pending, and CI gates consume them without scraping
            # log lines.
            return preview_entries

        self._record_applied_change_files(
            pending_change_files=pending_change_files,
            directive_outcomes=directive_outcomes,
            deployment_id=deployment_id,
        )
        status = self._compute_run_status(
            failed_count=len(failed),
            succeeded_count=succeeded_count,
        )
        self._finalize_run_record(
            deployment_id=deployment_id,
            started_at=started_at,
            status=status,
            structures_total=len(ordered_structures),
            structures_in_success=succeeded_count,
            structures_in_error=len(failed),
            structures_skipped=len(skipped),
        )
        if failed:
            failures = "; ".join(f"{name}: {error}" for name, error in failed.items())
            raise NldRuntimeException(
                f"Structure deploy ended '{status}' — "
                f"{len(failed)} of {len(ordered_structures)} structure(s) "
                f"failed ({len(skipped)} skipped): {failures}",
            )

        return True

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _preview_structure(
        self,
        deploy_manager: StructureDeployManager,
        namespaced_structure: NamespacedStructure,
        pending_field_renames: list[Any],
        pending_structure_renames: list[Any],
        pending_claiming_renames: list[Any],
        pending_backfill_defaults: list[BackfillDefaultDirective] | None = None,
    ) -> StructureChangeEntry | None:
        """Print the computed diff and DDL for one structure, execute nothing.

        The namespace and drift flags match the apply call exactly:
        preview must refuse on the same drift the apply would refuse
        on — a preview that hides a refusal is not a final review
        step. Returns the structured change entry, or None when the
        structure is in sync.
        """
        pending_backfill_defaults = pending_backfill_defaults or []
        structure = namespaced_structure.model
        change_set = deploy_manager.compute_change_set(
            structure=structure,
            allow_drift=self._allow_drift or self._adopt,
            namespace=namespaced_structure.namespace,
            pending_field_renames=pending_field_renames,
            pending_structure_renames=pending_structure_renames,
            pending_claiming_renames=pending_claiming_renames,
            pending_backfill_defaults=pending_backfill_defaults,
        )
        if (
            not change_set.diff.has_changes()
            and not change_set.statements
            and not pending_backfill_defaults
        ):
            return None

        summary = self._build_deploy_summary(
            structure=structure,
            diff=change_set.diff,
        )
        self.log_info(f"[PREVIEW] {summary}")
        for outcome_key, outcome in change_set.rename_outcomes.items():
            self.log_info(f"[PREVIEW] Pending directive {outcome_key}: {outcome}")
        for directive in pending_backfill_defaults:
            outcome_key = backfill_default_outcome_key(directive=directive)
            self.log_info(
                f"[PREVIEW] Pending directive {outcome_key}: "
                "would apply one-shot default fill",
            )
        for statement in change_set.statements:
            self.log_info(f"[PREVIEW] Would execute: {statement.sql}")

        if change_set.diff.is_new_table():
            action = StructureDeployAction.CREATE
        elif change_set.rebuild_required:
            action = StructureDeployAction.REBUILD
        elif change_set.diff.has_changes() or change_set.statements:
            action = StructureDeployAction.ALTER
        else:
            action = StructureDeployAction.NONE
        return StructureChangeEntry(
            action=action,
            characterisation_diffs=change_set.diff.characterisation_diffs,
            ddl_statements=[statement.sql for statement in change_set.statements],
            dependent_views=change_set.dependent_views,
            field_diffs=change_set.diff.field_diffs,
            namespace=namespaced_structure.namespace,
            structure_name=structure.name,
        )

    def _write_preview_output(
        self,
        preview_entries: list[StructureChangeEntry],
    ) -> None:
        """Write the previewed change entries as JSON when requested."""
        if self._output is None:
            return
        payload = [entry.to_dict(exclude_defaults=False) for entry in preview_entries]
        with open(self._output, "w", encoding="utf-8") as output_file:
            json.dump(payload, output_file, indent=2, default=str)
        self.log_info(f"Preview change entries written to {self._output}")

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _get_deploy_manager(
        self,
        namespace: str,
    ) -> StructureDeployManager:
        """Return the deploy manager for a structure's namespace mapping.

        One manager (and one schema-wide prefetch) is built per
        resolved (connection, schema) pair and reused across the
        structures that share it.
        """
        config = self.execution_context.project.structure_namespace_config
        mapping = config.get_mapping(namespace=namespace)
        if self._deploy_target_factory is None:
            self._deploy_target_factory = self._build_deploy_target_factory()
        return self._deploy_target_factory.get_manager(
            connection_name=mapping.default_connection_name,
            schema_name=mapping.schema_name,
        )

    def _build_deploy_target_factory(self) -> StructureDeployTargetFactory:
        """Build the run's shared per-(connection, schema) manager factory.

        Without a configured metadata backend connector each target
        keeps its metadata on its own connector, in the deploy schema
        itself.
        """
        metadata_backend_connector_name = (
            self.execution_context.project.metadata_backend_connector
        )
        metadata_connector: SQLDataConnector[Any] | None = None
        if metadata_backend_connector_name is not None:
            metadata_connector = cast(
                SQLDataConnector[Any],
                self.execution_context.get_data_connector(
                    metadata_backend_connector_name,
                    open_connection=True,
                ),
            )
        return StructureDeployTargetFactory(
            connector_resolver=self._resolve_sql_connector,
            metadata_connector=metadata_connector,
            variables=resolve_variables(
                project_variables=self.execution_context.project.variables,
            ),
        )

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

    def _validate_backfill_default_targets(
        self,
        backfill_defaults_by_structure: dict[str, list[BackfillDefaultDirective]],
    ) -> None:
        """Refuse a backfill_default directive that targets a view."""
        if not backfill_defaults_by_structure:
            return
        validate_backfill_default_targets(
            backfill_defaults_by_structure=backfill_defaults_by_structure,
            entity_registry=self.execution_context.entity_registry,
        )

    def _resolve_change_log(self) -> tuple[DeploymentChangeLogManager, str]:
        """Resolve the applied-log manager and its schema, once per run.

        The applied-log lives on the metadata backend connector's
        active schema so both the flow and the structure deploy paths
        share one exactly-once log per target. Resolved once — the
        load and record phases of one run must not each re-open the
        connector and re-ensure the table.
        """
        if self._change_log is not None:
            return self._change_log
        metadata_backend_connector_name = (
            self.execution_context.project.metadata_backend_connector
        )
        if metadata_backend_connector_name is None:
            raise NldRuntimeException(
                "metadata_backend_connector must be set in the project "
                "configuration to use deployment change files.",
            )
        metadata_connector = cast(
            SQLDataConnector[Any],
            self.execution_context.get_data_connector(
                metadata_backend_connector_name,
                open_connection=True,
            ),
        )
        change_log_schema = metadata_connector.get_active_schema()
        if change_log_schema is None:
            raise NldRuntimeException(
                "metadata_backend_connector must have a schema configured "
                "to host the deployment change applied-log.",
            )
        change_log_manager = DeploymentChangeLogManager(
            connector=metadata_connector,
        )
        change_log_manager.ensure_table(
            metadata_schema=change_log_schema,
        )
        self._change_log = (change_log_manager, change_log_schema)
        return self._change_log

    def _load_pending_change_files(
        self,
        deploy_scope: NamespaceDeployScope | None,
    ) -> list[PendingChangeFile]:
        """Load the pending deployment change files of the deploy scope."""
        change_log_manager, change_log_schema = self._resolve_change_log()
        pending = resolve_pending_change_files(
            project_root_folder_path=(
                self.execution_context.project.entities_root_folder_path
            ),
            applied_hashes_by_change_id=change_log_manager.get_applied_hashes(
                metadata_schema=change_log_schema,
            ),
            applied_directives_by_change_id=(
                change_log_manager.get_applied_directives(
                    metadata_schema=change_log_schema,
                )
            ),
        )
        if deploy_scope is not None:
            pending = scope_pending_change_files(
                pending_change_files=pending,
                is_directive_in_scope=deploy_scope.contains_directive,
            )
        if pending:
            pending_ids = ", ".join(change.change_id for change in pending)
            self.log_info(f"Pending deployment change file(s): {pending_ids}")
        return pending

    def _start_run_record(
        self,
        deployment_id: str,
        started_at: Any,
        structures_total: int,
        deploy_scope: NamespaceDeployScope | None = None,
    ) -> None:
        """Insert the run-level record and its scope at the start of an apply run.

        Recorded on the project's metadata backend connector; a
        project without one keeps per-target metadata only and has no
        run-level record to write to.
        """
        run_target = self._resolve_run_record_target()
        if run_target is None:
            return
        metadata_manager, metadata_schema = run_target
        metadata_manager.ensure_deploy_run_table(metadata_schema=metadata_schema)
        metadata_manager.insert_deploy_run(
            metadata_schema=metadata_schema,
            row=StructureDeployRunRow(
                deployment_id=deployment_id,
                started_at=started_at,
                structures_total=structures_total,
            ),
        )
        DeploymentScopeManager(
            connector=self._get_metadata_connector(),
        ).record(
            metadata_schema=metadata_schema,
            row=DeploymentScopeRow.build(
                deployment_id=deployment_id,
                command=STRUCTURE_DEPLOY_COMMAND,
                recorded_at=get_current_datetime(),
                requested_namespace=self._namespace,
                requested_name=self._name,
                unit_namespaces=(
                    [] if deploy_scope is None else deploy_scope.unit_namespaces
                ),
                deploy_groups=[] if deploy_scope is None else deploy_scope.groups,
                lock_keys=self._resolve_lock_keys(deploy_scope=deploy_scope),
            ),
        )

    def _hold_deploy_lock(
        self,
        deploy_scope: NamespaceDeployScope | None,
        deployment_id: str,
    ) -> AbstractContextManager[None]:
        """Return the deploy lock to hold while applying, if any.

        A preview changes nothing and takes no lock; a project without a
        metadata backend connector has no shared place to hold one.
        """
        run_target = None if self._preview else self._resolve_run_record_target()
        if run_target is None:
            return nullcontext()
        _, metadata_schema = run_target
        scope_description = (
            "the whole project" if deploy_scope is None else deploy_scope.describe()
        )
        if self._name is not None:
            scope_description += f", structure '{self._name}'"
        return DeploymentLockManager(
            connector=self._get_metadata_connector(),
        ).hold(
            metadata_schema=metadata_schema,
            lock_keys=self._resolve_lock_keys(deploy_scope=deploy_scope),
            holder_id=deployment_id,
            command=STRUCTURE_DEPLOY_COMMAND,
            scope=scope_description,
        )

    def _resolve_lock_keys(
        self,
        deploy_scope: NamespaceDeployScope | None,
    ) -> list[str]:
        """Return the keys of the deploy targets this run may change."""
        return resolve_lock_keys(
            deploy_scope=deploy_scope,
            structure_namespace_config=(
                self.execution_context.project.structure_namespace_config
            ),
        )

    def _get_metadata_connector(self) -> SQLDataConnector[Any]:
        """Open (or reuse) the project's metadata backend connector."""
        metadata_backend_connector_name = (
            self.execution_context.project.metadata_backend_connector
        )
        if metadata_backend_connector_name is None:
            raise NldRuntimeException(
                "metadata_backend_connector must be set in the project "
                "configuration to record deployment metadata.",
            )
        return self._resolve_sql_connector(
            connection_name=metadata_backend_connector_name,
        )

    def _finalize_run_record(
        self,
        deployment_id: str,
        started_at: Any,
        status: str,
        structures_total: int,
        structures_in_success: int,
        structures_in_error: int,
        structures_skipped: int,
    ) -> None:
        """Write the run's final status and counters."""
        run_target = self._resolve_run_record_target()
        if run_target is None:
            return
        metadata_manager, metadata_schema = run_target
        metadata_manager.update_deploy_run(
            metadata_schema=metadata_schema,
            row=StructureDeployRunRow(
                deployment_id=deployment_id,
                started_at=started_at,
                completed_at=get_current_datetime(),
                status=status,
                structures_total=structures_total,
                structures_in_success=structures_in_success,
                structures_in_error=structures_in_error,
                structures_skipped=structures_skipped,
            ),
        )

    def _resolve_run_record_target(
        self,
    ) -> tuple[StructureMetadataBackendManager, str] | None:
        """Resolve where run-level records live, when the project has one."""
        metadata_backend_connector_name = (
            self.execution_context.project.metadata_backend_connector
        )
        if metadata_backend_connector_name is None:
            return None
        metadata_connector = cast(
            SQLDataConnector[Any],
            self.execution_context.get_data_connector(
                metadata_backend_connector_name,
                open_connection=True,
            ),
        )
        metadata_schema = metadata_connector.get_active_schema()
        if metadata_schema is None:
            return None
        return (
            StructureMetadataBackendManager(metadata_connector=metadata_connector),
            metadata_schema,
        )

    @staticmethod
    def _compute_run_status(
        failed_count: int,
        succeeded_count: int,
    ) -> str:
        """Compute the run status with the flow-deploy semantics."""
        if failed_count > 0 and succeeded_count > 0:
            return "partial"
        if failed_count > 0:
            return "failed"
        return "success"

    def _record_applied_change_files(
        self,
        pending_change_files: list[PendingChangeFile],
        directive_outcomes: dict[str, str],
        deployment_id: str,
    ) -> None:
        """Record the resolved directives and completed change files.

        Each directive resolved in this run is recorded, so no later
        deploy applies it again; a change file joins the applied-log
        once every one of its directives is recorded — the reload and
        flow rename directives are resolved by ``nld flow deploy``.
        """
        if not pending_change_files:
            return
        change_log_manager, change_log_schema = self._resolve_change_log()

        change_log_manager.record_applied_directives(
            metadata_schema=change_log_schema,
            pending_change_files=pending_change_files,
            directive_outcomes=directive_outcomes,
            deployment_id=deployment_id,
        )

    def _order_rename_targets_first(
        self,
        structures_to_deploy: list[NamespacedStructure],
        structure_renames_by_target: dict[str, Any],
    ) -> list[NamespacedStructure]:
        """Move the targets of pending declared renames to the front.

        A rename target frees its old table name when it deploys;
        any structure reclaiming that name must come after it.
        """
        rename_targets: list[NamespacedStructure] = []
        others: list[NamespacedStructure] = []
        for namespaced_structure in structures_to_deploy:
            full_name = self._build_structure_full_name(
                namespaced_structure=namespaced_structure,
            )
            if full_name in structure_renames_by_target:
                rename_targets.append(namespaced_structure)
            else:
                others.append(namespaced_structure)
        return rename_targets + others

    @staticmethod
    def _build_structure_full_name(
        namespaced_structure: NamespacedStructure,
    ) -> str:
        """Build the namespace-qualified structure name."""
        return build_entity_key(
            namespace=namespaced_structure.namespace,
            entity_name=namespaced_structure.model.name,
        )

    def _resolve_namespace(
        self,
        namespace: str | None,
        structure_name: str | None,
    ) -> str | None:
        """Resolve the effective namespace, None for the whole project.

        When a structure_name is provided, retrieves the NamespacedStructure
        from the entity registry and uses its namespace.
        """
        if structure_name is not None:
            entity_registry = self.execution_context.entity_registry
            namespaced_structure = entity_registry.get_structure(
                entity_key=structure_name,
                namespace=namespace,
            )
            return namespaced_structure.namespace
        return namespace

    def _resolve_deploy_scope(
        self,
        namespace: str | None,
    ) -> NamespaceDeployScope | None:
        """Resolve the namespace deploy scope, None for a full-project deploy."""
        if namespace is None:
            return None
        project = self.execution_context.project
        deploy_scope = resolve_namespace_deploy_scope(
            namespace=namespace,
            structure_namespace_config=project.structure_namespace_config,
            deploy_namespace_config=project.deploy_namespace_config,
        )
        self.log_info(f"Deploy scope: {deploy_scope.describe()}")
        return deploy_scope

    def _load_structures_to_deploy(
        self,
        namespace: str | None,
        structure_name: str | None,
        deploy_scope: NamespaceDeployScope | None = None,
    ) -> list[NamespacedStructure]:
        """Load structures to deploy from the entity registry.

        A namespace deploy takes the structures of its deployment units
        only: the descendants mapped to another deploy target are left
        out and named, so their exclusion is visible.
        """
        entity_registry = self.execution_context.entity_registry
        if structure_name is not None:
            namespaced = entity_registry.get_structure(
                entity_key=structure_name,
                namespace=namespace,
            )
            if (
                namespaced.model.is_external_source()
                or namespaced.model.is_managed_by_flow_execution()
            ):
                return []
            if not namespaced.model.is_table():
                msg = (
                    f"Structure '{structure_name}' is of type "
                    f"'{namespaced.model.structure_type}' and cannot be deployed. "
                    f"Only TABLE structures are supported"
                )
                raise NldRuntimeException(msg)
            return [namespaced]

        structure_dict = entity_registry.get_structure_dict()
        if deploy_scope is not None:
            for excluded_namespace in deploy_scope.find_excluded_namespaces(
                namespaces=[
                    namespaced_structure.namespace
                    for namespaced_structure in structure_dict.values()
                ],
            ):
                self.log_info(
                    f"Namespace '{excluded_namespace}' deploys to another target — "
                    "excluded from this deploy",
                )
            structure_dict = {
                key: namespaced_structure
                for key, namespaced_structure in structure_dict.items()
                if deploy_scope.contains(namespace=namespaced_structure.namespace)
            }
        structures: list[NamespacedStructure] = []
        for namespaced_structure in structure_dict.values():
            if (
                namespaced_structure.model.is_table()
                and not namespaced_structure.model.is_external_source()
                and not namespaced_structure.model.is_managed_by_flow_execution()
            ):
                structures.append(namespaced_structure)
        return structures

    def _build_deploy_summary(
        self,
        structure: Structure,
        diff: StructureDiff,
    ) -> str:
        """Build a human-readable summary of deployed changes."""
        if not diff.has_changes() and not diff.is_new_table():
            return (
                f"Structure '{structure.name}' deployed: "
                f"definition updated (no schema changes)"
            )

        field_counts: dict[DiffAction, int] = {}
        for field_diff in diff.field_diffs:
            field_counts[field_diff.action] = field_counts.get(field_diff.action, 0) + 1

        char_counts: dict[DiffAction, int] = {}
        for char_diff in diff.characterisation_diffs:
            char_counts[char_diff.action] = char_counts.get(char_diff.action, 0) + 1

        parts = []
        if DiffAction.ADD in field_counts:
            parts.append(f"{field_counts[DiffAction.ADD]} field(s) added")
        if DiffAction.MODIFY in field_counts:
            parts.append(f"{field_counts[DiffAction.MODIFY]} field(s) modified")
        if DiffAction.DROP in field_counts:
            parts.append(f"{field_counts[DiffAction.DROP]} field(s) dropped")
        if DiffAction.ADD in char_counts:
            parts.append(
                f"{char_counts[DiffAction.ADD]} characterisation(s) added",
            )
        if DiffAction.MODIFY in char_counts:
            parts.append(
                f"{char_counts[DiffAction.MODIFY]} characterisation(s) modified",
            )
        if DiffAction.DROP in char_counts:
            parts.append(
                f"{char_counts[DiffAction.DROP]} characterisation(s) dropped",
            )

        action = "created" if diff.is_new_table() else "deployed"
        if not parts:
            return f"Structure '{structure.name}' {action}"
        detail = ", ".join(parts)
        return f"Structure '{structure.name}' {action}: {detail}"
