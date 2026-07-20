from __future__ import annotations

import dataclasses
import logging
from typing import Any

from nld.connector.base.connector import SQLDataConnector
from nld.connector.base.deploy_capabilities import ConnectorDeployCapabilities
from nld.connector.base.query import QueryExecResult
from nld.deploy.change_file_loader import ChangeFileError
from nld.deploy.change_file_models import (
    BackfillDefaultDirective,
    RenameFieldDirective,
    RenameStructureDirective,
    backfill_default_outcome_key,
    rename_structure_outcome_key,
)
from nld.exceptions import NldRuntimeException
from nld.pydantic.base_model import NldBaseModel
from nld.structure.deploy.deploy_snapshot import DeploySnapshot
from nld.structure.deploy.metadata_recorder import MetadataRecorder
from nld.structure.deploy.rebuild_strategy_builder import RebuildStrategyBuilder
from nld.structure.deploy.rename_resolver import (
    FieldRenameResolution,
    RenameResolver,
)
from nld.structure.deploy.structure_diff import (
    DiffAction,
    StructureDiff,
)
from nld.structure.deploy.structure_diff_computer import StructureDiffComputer
from nld.structure.deploy.structure_diff_ddl_statement_builder import DDLStatement
from nld.structure.deploy.structure_drift import (
    DeploymentDriftError,
    classify_drift,
)
from nld.structure.deploy.structure_metadata_backend_manager import (
    StructureMetadataBackendManager,
)
from nld.structure.deploy.structure_metadata_models import StructureMetadataRow
from nld.structure.deploy.structure_schema_history import (
    StructureSchemaHistoryRecord,
    StructureSchemaSnapshot,
    build_structure_snapshot_json,
    compute_structure_hash,
    compute_structure_schema_hash,
)
from nld.structure.structure.structure import NamespacedStructure, Structure
from nld.utils.datetime_util import get_current_datetime
from nld.utils.jinja_utils import render_template


def mint_backup_suffix() -> str:
    """Mint the wall-clock suffix for REBUILD backup table names.

    Minted once per deploy manager, so every statement computation the
    manager serves (preview, apply, re-plan) names the same backup.
    Microseconds keep two rebuilds of the same table in the same
    second from colliding.
    """
    return get_current_datetime().strftime("%Y%m%d%H%M%S%f")


def _raise_on_error_result(
    result: QueryExecResult,
    sql: str,
) -> None:
    """Fail loudly when the connector reports an error without raising.

    Some connectors (e.g. Snowflake) return an ERROR-status result
    instead of raising on a rejected statement — a failed DDL
    statement must surface as a failed deploy, never as a silent
    partial success.
    """
    result.raise_on_error(f"DDL statement failed: {sql}")


class StructureChangeSet(NldBaseModel):
    """Computed structure changes: diff and DDL statements.

    Pending declared renames resolve to leading rename statements;
    the diff is computed as if those renames were already applied.
    ``dependent_views`` lists the views (recursively, deepest first)
    that must be dropped before the table DDL and recreated by
    re-executing their flows afterwards.
    """

    dependent_views: list[str] = []
    diff: StructureDiff
    # True when the manager will apply this change set through the
    # backup REBUILD strategy (reorder, or default change on an engine
    # without ALTER COLUMN SET DEFAULT) — the preview action label
    # must come from this decision, not from re-deriving part of it.
    rebuild_required: bool = False
    rename_outcomes: dict[str, str] = {}
    statements: list[DDLStatement]


@dataclasses.dataclass(frozen=True)
class StructureDeployResult:
    """Result of a single structure deployment."""

    deployed: bool
    deployment_id: str | None
    diff: StructureDiff
    statements: list[DDLStatement]
    rename_outcomes: dict[str, str] = dataclasses.field(default_factory=dict)


class StructureDeployManager:
    """Deploys a single structure to the database.

    Handles diff computation, DDL generation and execution,
    and schema metadata recording for one structure at a time.
    """

    def __init__(
        self,
        structure_connector: SQLDataConnector[Any],
        deploy_schema: str,
        metadata_backend_connector: SQLDataConnector[Any] | None = None,
        metadata_schema: str | None = None,
        variables: dict[str, str] | None = None,
        snapshot: DeploySnapshot | None = None,
        backup_suffix: str | None = None,
    ) -> None:
        self._backup_suffix = backup_suffix or mint_backup_suffix()
        self._connector = structure_connector
        self._ddl_statement_builder = (
            structure_connector.get_structure_diff_ddl_statement_builder()
        )
        self._capabilities: ConnectorDeployCapabilities = (
            structure_connector.get_deploy_capabilities()
        )
        self._diff_computer = StructureDiffComputer(
            capabilities=self._capabilities,
        )
        self._deploy_schema = deploy_schema
        self._variables = variables or {}
        self._metadata_manager = (
            StructureMetadataBackendManager(
                metadata_connector=metadata_backend_connector,
            )
            if metadata_backend_connector is not None
            else None
        )
        self._metadata_schema = metadata_schema
        self._reader = structure_connector.get_structure_reader()

        # The live-state snapshot of the deploy target, ideally built
        # once per (connector, schema) per run by the caller
        # (prefetched) and shared across managers so planning and
        # applying read the same state. A manager built without one
        # (tests, ad-hoc scripts) gets a private, unprefetched
        # snapshot: correct, if unbatched, behavior.
        self._snapshot = snapshot or DeploySnapshot(
            connector=structure_connector,
            deploy_schema=deploy_schema,
            metadata_manager=self._metadata_manager,
            metadata_schema=metadata_schema,
        )
        self._rename_resolver = RenameResolver(
            snapshot=self._snapshot,
            ddl_statement_builder=self._ddl_statement_builder,
            capabilities=self._capabilities,
            deploy_schema=deploy_schema,
        )
        self._rebuild_strategy_builder = RebuildStrategyBuilder(
            ddl_statement_builder=self._ddl_statement_builder,
            capabilities=self._capabilities,
            deploy_schema=deploy_schema,
            backup_suffix=self._backup_suffix,
        )
        self._metadata_recorder = (
            MetadataRecorder(
                metadata_manager=self._metadata_manager,
                metadata_schema=metadata_schema,
                deploy_schema=deploy_schema,
                snapshot=self._snapshot,
            )
            if self._metadata_manager is not None and metadata_schema is not None
            else None
        )

    def compute_change_set(
        self,
        structure: Structure,
        allow_drift: bool = False,
        namespace: str | None = None,
        pending_field_renames: list[RenameFieldDirective] | None = None,
        pending_structure_renames: list[RenameStructureDirective] | None = None,
        pending_claiming_renames: list[RenameStructureDirective] | None = None,
        pending_backfill_defaults: list[BackfillDefaultDirective] | None = None,
    ) -> StructureChangeSet:
        """Compute diff and DDL statements without executing or recording metadata.

        Pending declared renames resolve first — the table rename,
        then the field renames on the (possibly renamed) table. The
        rename statements lead the DDL and the diff is computed as if
        the renames were already applied, so a declared rename never
        reads as a destructive drop-and-add.

        ``pending_claiming_renames`` are directives moving *another*
        asset away from this structure's name: the live table (and
        the recorded state) under this name belong to that other
        asset, so the change set is computed as a plain CREATE and
        the drift gate is skipped — never a destructive ALTER of a
        table this structure does not own.

        When a metadata backend is configured, unexplained drift
        between the live schema and the recorded state refuses the
        computation (pass ``allow_drift=True`` to proceed anyway).

        A pending ``backfill_default`` targeting a VIEW is a hard
        error, checked here so it fails loudly at preview time too —
        a view has no physical column to fill.
        """
        self._validate_backfill_defaults_target_table(
            structure=structure,
            pending_backfill_defaults=pending_backfill_defaults or [],
        )
        pending_claiming_renames = pending_claiming_renames or []
        if not allow_drift and namespace is not None and not pending_claiming_renames:
            self._check_drift(
                structure=structure,
                namespace=namespace,
                pending_field_renames=pending_field_renames or [],
                pending_structure_renames=pending_structure_renames or [],
            )
        table_resolution = self._resolve_structure_renames(
            structure=structure,
            pending_structure_renames=pending_structure_renames or [],
        )
        if pending_claiming_renames and table_resolution.current is not None:
            table_resolution = dataclasses.replace(
                table_resolution,
                current=None,
            )
        field_resolution = self._resolve_field_renames(
            structure=structure,
            current=table_resolution.current,
            pending_field_renames=pending_field_renames or [],
        )
        diff = self._diff_computer.compute(
            desired=structure,
            current=field_resolution.current,
        )
        # An order mismatch (a genuine reorder, or a new field that is
        # declared before an existing one on engines without a
        # positional ADD COLUMN) is impossible in place; a default
        # change is impossible in place on engines without ALTER
        # COLUMN SET DEFAULT (Snowflake allows it for sequences only).
        # The REBUILD strategy replaces the field-level ALTER path
        # entirely (additions and drops resolve through the rebuilt
        # table as well, so any number of added fields lands in one
        # single rebuild). The declared renames still lead so the
        # copy reads the renamed columns.
        needs_default_rebuild = not self._capabilities.alter_column_set_default and any(
            field_diff.action == DiffAction.MODIFY and field_diff.default_to is not None
            for field_diff in diff.field_diffs
        )
        rebuild_required = (
            diff.order_mismatch or needs_default_rebuild
        ) and field_resolution.current is not None
        if rebuild_required and field_resolution.current is not None:
            deploy_statements = self._build_rebuild_backup_statements(
                structure=structure,
                current=field_resolution.current,
            )
        else:
            deploy_statements = self._generate_statements(
                diff=diff,
                structure=structure,
            )

        dependent_views: list[str] = []
        view_drop_statements: list[DDLStatement] = []
        if self._change_requires_dependent_view_handling(diff=diff):
            if not self._capabilities.detects_dependent_views:
                logging.getLogger(__name__).warning(
                    "The '%s' engine cannot detect dependent views — "
                    "verify manually that no view depends on '%s' "
                    "before this change applies.",
                    self._capabilities.dialect,
                    structure.name,
                )
            dependent_views = self.find_dependent_views(
                table_name=structure.name,
            )
            view_drop_statements = [
                self._ddl_statement_builder.build_drop_view_statement(
                    schema_name=self._deploy_schema,
                    view_name=view_name,
                )
                for view_name in dependent_views
            ]

        statements = (
            view_drop_statements
            + table_resolution.statements
            + field_resolution.statements
            + deploy_statements
        )
        return StructureChangeSet(
            dependent_views=dependent_views,
            diff=diff,
            rebuild_required=rebuild_required,
            rename_outcomes={
                **table_resolution.outcomes,
                **field_resolution.outcomes,
            },
            statements=statements,
        )

    def deploy(
        self,
        namespaced_structure: NamespacedStructure,
        adopt: bool = False,
        allow_dependent_view_drops: bool = False,
        allow_drift: bool = False,
        pending_field_renames: list[RenameFieldDirective] | None = None,
        pending_structure_renames: list[RenameStructureDirective] | None = None,
        pending_claiming_renames: list[RenameStructureDirective] | None = None,
        pending_backfill_defaults: list[BackfillDefaultDirective] | None = None,
        rebuild: bool = False,
    ) -> StructureDeployResult:
        """Deploy a single structure to the database.

        Computes lightweight hashes early to skip expensive operations
        when nothing has changed since the last deployment.

        Args:
            namespaced_structure: The structure definition with its
                namespace to deploy.
            adopt: Record the live schema as a flagged state-refresh
                baseline before deploying (drift reconciliation).
            allow_dependent_view_drops: Drop the dependent views a
                change requires instead of refusing. The caller owns
                their recreation: the flow deploy path re-executes
                their VIEW flows, the structure adopt path leaves
                them to the next flow deploy.
            allow_drift: Deploy against the live schema even when
                it drifted from the recorded state.
            pending_field_renames: Declared field renames not yet in
                the applied-log, resolved against the live table
                before the diff.
            pending_structure_renames: Declared table renames whose
                target is this structure, resolved before the field
                renames.
            pending_claiming_renames: Declared table renames moving
                another asset away from this structure's name. The
                deploy refuses while the claimed table still exists
                (the rename target must deploy first) and otherwise
                proceeds as a plain CREATE with a fresh identity.
            pending_backfill_defaults: Declared one-shot default fills
                targeting this structure, applied after the DDL and
                hooks so an added/renamed column exists first. Refused
                when the structure is a VIEW.
            rebuild: Recreate the structure from the asset, ignoring
                both the recorded and the live state.

        Returns:
            A StructureDeployResult with the deployment outcome,
            diff, and generated DDL statements.
        """
        pending_field_renames = pending_field_renames or []
        pending_structure_renames = pending_structure_renames or []
        pending_claiming_renames = pending_claiming_renames or []
        pending_backfill_defaults = pending_backfill_defaults or []
        if self._metadata_manager is None or self._metadata_schema is None:
            raise NldRuntimeException(
                "metadata_manager and metadata_schema are required for deploy()"
            )

        namespace = namespaced_structure.namespace
        structure = namespaced_structure.model

        if pending_claiming_renames and not rebuild:
            self._refuse_while_name_is_claimed(
                structure=structure,
                pending_claiming_renames=pending_claiming_renames,
            )

        if rebuild:
            return self._deploy_rebuild(
                namespaced_structure=namespaced_structure,
            )

        schema_snapshot = StructureSchemaSnapshot.from_structure(
            structure=structure,
            namespace=namespace,
            capabilities=self._capabilities,
        )
        new_schema_hash = compute_structure_schema_hash(
            schema_snapshot=schema_snapshot,
        )
        new_structure_hash = compute_structure_hash(structure=structure)

        adopt_found_live_state = True
        if adopt:
            adopt_found_live_state = self._adopt_current_state(
                namespaced_structure=namespaced_structure,
            )

        previous_row = self._get_state_row(
            namespace=namespace,
            structure_name=structure.name,
        )
        prev_schema_hash = (
            previous_row.structure_schema_hash if previous_row is not None else None
        )
        prev_structure_hash = (
            previous_row.structure_hash if previous_row is not None else None
        )

        schema_hash_unchanged = (
            prev_schema_hash is not None and prev_schema_hash == new_schema_hash
        )
        structure_hash_unchanged = (
            prev_structure_hash is not None
            and prev_structure_hash == new_structure_hash
        )

        # Pending renames must resolve against the live table even
        # when the recorded hashes look current, so the early exit
        # only applies with no pending directives. Drift still needs
        # detecting on an unchanged definition (pure A−R drift), so
        # the drift gate runs before the early exit; with allow_drift
        # the deploy must reach the actual schema, so no early exit.
        # An adopt that found no live table must also fall through:
        # the recorded hashes describe a table that no longer exists,
        # and the deploy below recreates it from the asset.
        if (
            not pending_field_renames
            and not pending_structure_renames
            and not pending_claiming_renames
            and not pending_backfill_defaults
            and not allow_drift
            and adopt_found_live_state
            and schema_hash_unchanged
            and structure_hash_unchanged
        ):
            if not allow_drift and not adopt:
                self._check_drift(
                    structure=structure,
                    namespace=namespace,
                    pending_field_renames=pending_field_renames,
                    pending_structure_renames=pending_structure_renames,
                )
            empty_diff = StructureDiff(
                structure_name=structure.name,
                table_exists=True,
            )
            return StructureDeployResult(
                deployed=False,
                deployment_id=None,
                diff=empty_diff,
                statements=[],
            )

        change_set = self.compute_change_set(
            structure=structure,
            allow_drift=allow_drift or adopt,
            namespace=namespace,
            pending_field_renames=pending_field_renames,
            pending_structure_renames=pending_structure_renames,
            pending_claiming_renames=pending_claiming_renames,
            pending_backfill_defaults=pending_backfill_defaults,
        )
        if change_set.dependent_views and not allow_dependent_view_drops:
            dependent_names = ", ".join(change_set.dependent_views)
            raise NldRuntimeException(
                f"Changing structure '{structure.name}' requires dropping "
                f"dependent view(s) [{dependent_names}]. Run `nld flow "
                "deploy`, which recreates them by re-executing their VIEW "
                "flows — nothing was dropped.",
            )
        diff = change_set.diff
        statements = change_set.statements

        has_schema_changes = diff.has_changes() or len(statements) > 0
        has_definition_changes = not structure_hash_unchanged

        if (
            not has_schema_changes
            and not has_definition_changes
            and not pending_backfill_defaults
        ):
            return StructureDeployResult(
                deployed=False,
                deployment_id=None,
                diff=diff,
                statements=statements,
                rename_outcomes=change_set.rename_outcomes,
            )

        ddl_applied = False
        self.execute_pre_deployment_hooks(structure=structure)
        if has_schema_changes and statements:
            self._execute_statements(statements=statements)
            ddl_applied = True
            self._update_current_structure_cache_after_ddl(
                structure=structure,
                pending_structure_renames=pending_structure_renames,
                rename_outcomes=change_set.rename_outcomes,
            )

        self.execute_post_deployment_hooks(structure=structure)

        backfill_outcomes = self._apply_backfill_defaults(
            structure=structure,
            pending_backfill_defaults=pending_backfill_defaults,
        )

        structure_deployment_id = self._write_schema_metadata_on_backend(
            namespaced_structure=namespaced_structure,
            schema_snapshot=schema_snapshot,
            structure_schema_hash=new_schema_hash,
            structure_hash=new_structure_hash,
            diff=diff,
            statements=statements if has_schema_changes else [],
            ddl_applied=ddl_applied,
            pending_structure_renames=pending_structure_renames,
        )

        return StructureDeployResult(
            deployed=True,
            deployment_id=structure_deployment_id,
            diff=diff,
            statements=statements,
            rename_outcomes={**change_set.rename_outcomes, **backfill_outcomes},
        )

    def _update_current_structure_cache_after_ddl(
        self,
        structure: Structure,
        pending_structure_renames: list[RenameStructureDirective],
        rename_outcomes: dict[str, str],
    ) -> None:
        """Keep the current-structure cache accurate after this structure's DDL.

        A rename applied in this call frees its old physical name —
        a later structure in the same run reclaiming that name (see
        ``_refuse_while_name_is_claimed``) must see it as free without
        a re-query. The structure's own name now reflects the
        just-applied diff, so it is refreshed with the deployed
        definition rather than left at its pre-DDL snapshot.
        """
        for directive in pending_structure_renames:
            outcome_key = rename_structure_outcome_key(directive=directive)
            if rename_outcomes.get(outcome_key) == "renamed":
                old_table_name = directive.from_name.split(".")[-1]
                self._snapshot.forget_live_object(table_name=old_table_name)
        self._snapshot.set_live_structure(structure=structure)

    def _refuse_while_name_is_claimed(
        self,
        structure: Structure,
        pending_claiming_renames: list[RenameStructureDirective],
    ) -> None:
        """Refuse the deploy while the live table belongs to another asset.

        The structure reclaims a name a pending rename directive is
        moving another asset away from. Deploying before that rename
        ran would ALTER (or replace) a table this structure does not
        own — the rename target must deploy first. A full deploy
        orders the rename targets automatically; a scoped deploy must
        widen its scope to include the rename target.
        """
        if self._read_current_structure(structure=structure) is None:
            return
        directive_keys = ", ".join(
            rename_structure_outcome_key(directive=directive)
            for directive in pending_claiming_renames
        )
        raise ChangeFileError(
            f"Cannot deploy structure '{structure.name}': the live table "
            f"'{self._deploy_schema}.{structure.name}' still belongs to "
            f"another asset with a pending declared rename ({directive_keys}). "
            "Deploy the rename target first — a full deploy orders it "
            "automatically; a scoped deploy must include the rename target.",
        )

    @staticmethod
    def _validate_backfill_defaults_target_table(
        structure: Structure,
        pending_backfill_defaults: list[BackfillDefaultDirective],
    ) -> None:
        """Refuse backfill_default directives that target a view.

        backfill_default is a one-shot UPDATE against a physical
        column; a view has none. This is a hard error — never a
        silent no-op — regardless of preview or apply.
        """
        if not pending_backfill_defaults or not structure.is_view():
            return
        directive_keys = ", ".join(
            backfill_default_outcome_key(directive=directive)
            for directive in pending_backfill_defaults
        )
        raise ChangeFileError(
            f"Cannot apply backfill_default to '{structure.name}': it is a "
            f"VIEW and has no physical column to backfill ({directive_keys}).",
        )

    def _apply_backfill_defaults(
        self,
        structure: Structure,
        pending_backfill_defaults: list[BackfillDefaultDirective],
    ) -> dict[str, str]:
        """Fill a column for existing rows, once, from the declared rule.

        Runs after the DDL and hooks so an added or renamed column
        exists before the UPDATE executes. This is a one-shot data
        operation against the structure's own physical table — it has
        nothing to do with any flow, and does not participate in the
        schema diff.
        """
        outcomes: dict[str, str] = {}
        for directive in pending_backfill_defaults:
            outcome_key = backfill_default_outcome_key(directive=directive)
            update_sql = (
                f"UPDATE {self._deploy_schema}.{structure.name} "
                f"SET {directive.field} = {directive.value} "
                f"WHERE {directive.field} IS NULL"
            )
            result = self._connector.execute_query(update_sql)
            _raise_on_error_result(result=result, sql=update_sql)
            self._connector.commit()
            # The row count is the number an operator wants when
            # auditing a one-shot data fill.
            outcomes[outcome_key] = (
                f"applied (one-shot default fill, {result.get_row_count()} rows)"
            )
        return outcomes

    def _check_drift(
        self,
        structure: Structure,
        namespace: str,
        pending_field_renames: list[RenameFieldDirective],
        pending_structure_renames: list[RenameStructureDirective],
    ) -> None:
        """Refuse the deploy when the live schema drifted unexpectedly.

        Compares the live schema (A) against the recorded state (R);
        differences the intended change (D − R) or a pending declared
        rename cannot explain are unexpected drift. Skipped for
        pending table renames — their resolution validates the live
        state on its own.
        """
        if self._metadata_manager is None or self._metadata_schema is None:
            return
        if pending_structure_renames:
            return

        previous_row = self._get_state_row(
            namespace=namespace,
            structure_name=structure.name,
        )
        if previous_row is None:
            return

        actual = self._read_current_structure(structure=structure)
        actual_snapshot = (
            StructureSchemaSnapshot.from_structure(
                structure=actual,
                namespace=namespace,
                capabilities=self._capabilities,
            )
            if actual is not None
            else None
        )
        if (
            actual_snapshot is not None
            and compute_structure_schema_hash(schema_snapshot=actual_snapshot)
            == previous_row.structure_schema_hash
        ):
            return

        expected_extra_field_names = {
            name
            for directive in pending_field_renames
            for name in (directive.from_name, directive.to)
        }
        report = classify_drift(
            structure_name=structure.name,
            recorded_snapshot=StructureSchemaSnapshot.model_validate_json(
                previous_row.structure_schema_snapshot,
            ),
            actual_snapshot=actual_snapshot,
            desired_snapshot=StructureSchemaSnapshot.from_structure(
                structure=structure,
                namespace=namespace,
                capabilities=self._capabilities,
            ),
            expected_extra_field_names=expected_extra_field_names,
            capabilities=self._capabilities,
        )
        if report.has_unexpected_drift():
            raise DeploymentDriftError(report.build_error_message())

    def _adopt_current_state(
        self,
        namespaced_structure: NamespacedStructure,
    ) -> bool:
        """Record the live schema as a flagged state-refresh baseline.

        Inserts a new record (never overwrites): the history keeps
        the fact that this baseline came from adopting out-of-band
        state rather than from a deployment.

        Returns whether a live table was found: a missing table has
        no state to adopt, and the caller must redeploy (recreate)
        instead of trusting the recorded hashes.
        """
        if self._metadata_manager is None or self._metadata_schema is None:
            raise NldRuntimeException(
                "A metadata backend is required for this operation.",
            )

        namespace = namespaced_structure.namespace
        structure = namespaced_structure.model
        actual = self._read_current_structure(structure=structure)
        if actual is None:
            return False

        previous_row = self._get_state_row(
            namespace=namespace,
            structure_name=structure.name,
        )
        actual_snapshot = StructureSchemaSnapshot.from_structure(
            structure=actual,
            namespace=namespace,
            capabilities=self._capabilities,
        )
        actual_schema_hash = compute_structure_schema_hash(
            schema_snapshot=actual_snapshot,
        )
        if (
            previous_row is not None
            and previous_row.structure_schema_hash == actual_schema_hash
        ):
            return True

        record = StructureSchemaHistoryRecord.build(
            namespace=namespace,
            object_path=self._deploy_schema,
            structure_name=structure.name,
            structure_schema_snapshot=actual_snapshot,
            structure_snapshot=build_structure_snapshot_json(structure=actual),
            structure_schema_hash=actual_schema_hash,
            structure_hash=compute_structure_hash(structure=actual),
            ddl_applied=False,
            previous_deployment_id=(
                previous_row.deployment_id if previous_row is not None else None
            ),
            record_source="state_refresh",
            uid=previous_row.uid if previous_row is not None else None,
        )
        self._metadata_manager.write_history_record(
            metadata_schema=self._metadata_schema,
            record=record,
        )
        self._metadata_manager.upsert_current_schema(
            metadata_schema=self._metadata_schema,
            record=record,
        )
        # `deploy()` re-reads this structure's state row right after
        # calling `_adopt_current_state`, in the same call — the cache
        # must reflect the row just written, not the pre-adopt one.
        self._snapshot.set_state_row(
            namespace=namespace,
            structure_name=structure.name,
            row=StructureMetadataRow.from_history_record(record=record),
        )
        return True

    def _build_rebuild_backup_statements(
        self,
        structure: Structure,
        current: Structure,
    ) -> list[DDLStatement]:
        """Build the backup-create-reinsert statements of the REBUILD strategy."""
        return self._rebuild_strategy_builder.build_backup_statements(
            structure=structure,
            current=current,
        )

    def compute_rebuild_statements(
        self,
        structure: Structure,
    ) -> list[DDLStatement]:
        """Compute the drop-and-recreate statements of the rebuild mode."""
        return self._rebuild_strategy_builder.build_drop_and_recreate_statements(
            structure=structure,
        )

    def _deploy_rebuild(
        self,
        namespaced_structure: NamespacedStructure,
    ) -> StructureDeployResult:
        """Recreate the structure from the asset, ignoring current state."""
        if self._metadata_manager is None or self._metadata_schema is None:
            raise NldRuntimeException(
                "A metadata backend is required for this operation.",
            )

        namespace = namespaced_structure.namespace
        structure = namespaced_structure.model

        statements = self.compute_rebuild_statements(structure=structure)
        self.execute_pre_deployment_hooks(structure=structure)
        self._execute_statements(statements=statements)
        self._snapshot.set_live_structure(structure=structure)
        self.execute_post_deployment_hooks(structure=structure)

        schema_snapshot = StructureSchemaSnapshot.from_structure(
            structure=structure,
            namespace=namespace,
            capabilities=self._capabilities,
        )
        rebuild_diff = StructureDiff(
            structure_name=structure.name,
            table_exists=False,
        )
        structure_deployment_id = self._write_schema_metadata_on_backend(
            namespaced_structure=namespaced_structure,
            schema_snapshot=schema_snapshot,
            structure_schema_hash=compute_structure_schema_hash(
                schema_snapshot=schema_snapshot,
            ),
            structure_hash=compute_structure_hash(structure=structure),
            diff=rebuild_diff,
            statements=statements,
            ddl_applied=True,
        )
        return StructureDeployResult(
            deployed=True,
            deployment_id=structure_deployment_id,
            diff=rebuild_diff,
            statements=statements,
        )

    @staticmethod
    def _change_requires_dependent_view_handling(
        diff: StructureDiff,
    ) -> bool:
        """Return True when the computed change can break dependent views.

        Column type changes and drops are blocked by PostgreSQL when
        a view references the column, and a REBUILD moves the whole
        table; additions never affect an existing view definition.
        """
        if diff.order_mismatch:
            return True
        return any(
            field_diff.action in (DiffAction.DROP, DiffAction.MODIFY)
            for field_diff in diff.field_diffs
        )

    def find_dependent_views(
        self,
        table_name: str,
    ) -> list[str]:
        """Find the views depending on a table, recursively, deepest first.

        Views can depend on views: the drop order returned removes
        the deepest dependents first so every DROP VIEW succeeds
        without cascading. The BFS walks the schema-wide dependency
        graph in memory instead of issuing one query per frontier
        node.
        """
        graph = self._get_dependent_views_graph()
        ordered_views: list[str] = []
        frontier = [table_name]
        seen: set[str] = set()
        while frontier:
            current_name = frontier.pop(0)
            for view_name in graph.get(current_name, []):
                if view_name in seen:
                    continue
                seen.add(view_name)
                ordered_views.append(view_name)
                frontier.append(view_name)
        return list(reversed(ordered_views))

    def _get_dependent_views_graph(self) -> dict[str, list[str]]:
        """Return the schema's view-dependency graph, fetched once per run."""
        return self._snapshot.dependent_views_graph()

    def _read_current_structure(
        self,
        structure: Structure,
    ) -> Structure | None:
        """Read the live structure from the target database."""
        return self._read_table(table_name=structure.name)

    def _read_table(
        self,
        table_name: str,
    ) -> Structure | None:
        """Read a live table by physical name, via the snapshot cache."""
        return self._snapshot.read_table(table_name=table_name)

    def _get_state_row(
        self,
        namespace: str,
        structure_name: str,
    ) -> StructureMetadataRow | None:
        """Read the recorded state row of a structure, via the snapshot cache."""
        return self._snapshot.get_state_row(
            namespace=namespace,
            structure_name=structure_name,
        )

    def _resolve_structure_renames(
        self,
        structure: Structure,
        pending_structure_renames: list[RenameStructureDirective],
    ) -> FieldRenameResolution:
        """Resolve the pending table renames targeting this structure."""
        return self._rename_resolver.resolve_structure_renames(
            structure=structure,
            pending_structure_renames=pending_structure_renames,
        )

    def _resolve_field_renames(
        self,
        structure: Structure,
        current: Structure | None,
        pending_field_renames: list[RenameFieldDirective],
    ) -> FieldRenameResolution:
        """Resolve the pending field renames against the live structure."""
        return self._rename_resolver.resolve_field_renames(
            structure=structure,
            current=current,
            pending_field_renames=pending_field_renames,
        )

    def _generate_statements(
        self,
        diff: StructureDiff,
        structure: Structure,
    ) -> list[DDLStatement]:
        """Generate DDL statements from a diff."""
        return self._ddl_statement_builder.build_ddl_statements(
            diff=diff,
            structure=structure,
            schema_name=self._deploy_schema,
        )

    def _build_hook_template_variables(
        self,
        structure: Structure,
    ) -> dict[str, str]:
        """Build the Jinja template variables available in structure-level hooks.

        Custom hook variables (from project config and env vars) are
        included but cannot shadow built-in variables.
        """
        return {
            **self._variables,
            "schema": self._deploy_schema,
            "structure_name": structure.name,
            "object_path": f"{self._deploy_schema}.{structure.name}",
        }

    def execute_pre_deployment_hooks(
        self,
        structure: Structure,
    ) -> None:
        """Execute the pre-deployment SQL hooks, before any DDL runs."""
        self._execute_hooks(
            structure=structure,
            hooks=structure.get_all_pre_deployment_sql_hooks(),
        )

    def execute_post_deployment_hooks(
        self,
        structure: Structure,
    ) -> None:
        """Execute the post-deployment SQL hooks, after all DDL ran."""
        self._execute_hooks(
            structure=structure,
            hooks=structure.get_all_post_deployment_sql_hooks(),
        )

    def _execute_hooks(
        self,
        structure: Structure,
        hooks: list[str],
    ) -> None:
        """Execute SQL hooks rendered with the structure template variables."""
        if not hooks:
            return
        template_variables = self._build_hook_template_variables(
            structure=structure,
        )
        for hook in hooks:
            sql = render_template(
                hook,
                **template_variables,
            )
            result = self._connector.execute_query(sql)
            _raise_on_error_result(result=result, sql=sql)
        self._connector.commit()

    def _execute_statements(
        self,
        statements: list[DDLStatement],
    ) -> None:
        """Execute DDL statements against the database."""
        for statement in statements:
            result = self._connector.execute_query(statement.sql)
            _raise_on_error_result(result=result, sql=statement.sql)

    def _write_schema_metadata_on_backend(
        self,
        namespaced_structure: NamespacedStructure,
        schema_snapshot: StructureSchemaSnapshot,
        structure_schema_hash: str,
        structure_hash: str,
        diff: StructureDiff,
        statements: list[DDLStatement],
        ddl_applied: bool,
        pending_structure_renames: list[RenameStructureDirective] | None = None,
    ) -> str:
        """Write metadata after deployment using precomputed snapshot and hashes.

        Returns the deployment_id of the created record.
        """
        if self._metadata_recorder is None:
            raise NldRuntimeException(
                "A metadata backend is required to record a deployment.",
            )
        return self._metadata_recorder.write_schema_metadata(
            namespaced_structure=namespaced_structure,
            schema_snapshot=schema_snapshot,
            structure_schema_hash=structure_schema_hash,
            structure_hash=structure_hash,
            diff=diff,
            statements=statements,
            ddl_applied=ddl_applied,
            pending_structure_renames=pending_structure_renames,
        )
