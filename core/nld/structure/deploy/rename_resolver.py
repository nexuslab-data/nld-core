from __future__ import annotations

import dataclasses
from typing import Any

from nld.connector.base.deploy_capabilities import ConnectorDeployCapabilities
from nld.deploy.change_file_loader import ChangeFileError
from nld.deploy.change_file_models import (
    RenameFieldDirective,
    RenameStructureDirective,
    rename_field_outcome_key,
    rename_structure_outcome_key,
)
from nld.structure.deploy.deploy_snapshot import DeploySnapshot
from nld.structure.deploy.structure_diff_ddl_statement_builder import (
    BaseStructureDiffDDLStatementBuilder,
    DDLStatement,
)
from nld.structure.structure.structure import Structure


@dataclasses.dataclass(frozen=True)
class FieldRenameResolution:
    """Pending renames resolved against the live structure."""

    current: Any
    outcomes: dict[str, str]
    statements: list[DDLStatement]


class RenameResolver:
    """Resolves pending declared renames against the live target.

    Declared renames (table and field) lead the DDL and the diff is
    computed as if they were already applied, so a rename never reads
    as a destructive drop-and-add. Every directive resolves to an
    explicit outcome — applied, verified no-op, or inconsistency
    error — recorded for the applied-change log.
    """

    def __init__(
        self,
        snapshot: DeploySnapshot,
        ddl_statement_builder: BaseStructureDiffDDLStatementBuilder,
        capabilities: ConnectorDeployCapabilities,
        deploy_schema: str,
    ) -> None:
        self._snapshot = snapshot
        self._ddl_statement_builder = ddl_statement_builder
        self._capabilities = capabilities
        self._deploy_schema = deploy_schema

    def resolve_structure_renames(
        self,
        structure: Structure,
        pending_structure_renames: list[RenameStructureDirective],
    ) -> FieldRenameResolution:
        """Resolve the pending table renames targeting this structure.

        The live table carries the old name and not the new one → a
        rename statement leads the DDL; it already carries the new
        name → a verified no-op (a rebuilt environment); neither →
        no-op, the CREATE will use the new name directly. Both is an
        inconsistency error.
        """
        current = self._snapshot.read_table(table_name=structure.name)
        outcomes: dict[str, str] = {}
        statements: list[DDLStatement] = []

        for directive in pending_structure_renames:
            outcome_key = rename_structure_outcome_key(directive=directive)
            old_table_name = directive.from_name.split(".")[-1]
            old_current = self._snapshot.read_table(table_name=old_table_name)

            if current is not None and old_current is None:
                outcomes[outcome_key] = "no-op (already effective)"
            elif current is None and old_current is not None:
                if not self._capabilities.rename_table_in_place:
                    raise ChangeFileError(
                        f"Cannot apply {outcome_key}: the "
                        f"'{self._capabilities.dialect}' engine has no "
                        "in-place table rename — a data-preserving "
                        "REBUILD is required and not implemented yet.",
                    )
                statements.append(
                    self._ddl_statement_builder.build_rename_table_statement(
                        schema_name=self._deploy_schema,
                        from_name=old_table_name,
                        to_name=structure.name,
                    ),
                )
                current = old_current.model_copy(
                    update={"name": structure.name},
                )
                outcomes[outcome_key] = "renamed"
            elif current is None and old_current is None:
                outcomes[outcome_key] = "no-op (table does not exist)"
            else:
                raise ChangeFileError(
                    f"Cannot apply {outcome_key}: both tables exist in "
                    f"schema '{self._deploy_schema}'.",
                )

        return FieldRenameResolution(
            current=current,
            outcomes=outcomes,
            statements=statements,
        )

    def resolve_field_renames(
        self,
        structure: Structure,
        current: Structure | None,
        pending_field_renames: list[RenameFieldDirective],
    ) -> FieldRenameResolution:
        """Resolve the pending field renames against the live structure.

        Resolution per directive: the live table has the old column and
        not the new one → a rename statement; it has *both* (a different
        column already holds the target name) → the declared rename
        wins, so the occupant is dropped and the rename applied — its
        data is intentionally replaced and the drop is surfaced in the
        preview; it already has the new column and not the old one → a
        verified no-op (a rebuilt environment); neither → an
        inconsistency error. The returned current structure has the
        renames applied in memory so the subsequent diff never sees a
        drop-and-add.
        """
        outcomes: dict[str, str] = {}
        statements: list[DDLStatement] = []
        adjusted = current

        for directive in pending_field_renames:
            outcome_key = rename_field_outcome_key(directive=directive)
            if adjusted is None:
                outcomes[outcome_key] = "no-op (table does not exist)"
                continue

            has_from = directive.from_name in adjusted.fields
            has_to = directive.to in adjusted.fields

            if has_from:
                if not self._capabilities.rename_column_in_place:
                    raise ChangeFileError(
                        f"Cannot apply {outcome_key}: the "
                        f"'{self._capabilities.dialect}' engine has no "
                        "in-place column rename — a data-preserving "
                        "REBUILD is required and not implemented yet.",
                    )
                if has_to:
                    # A different live column already holds the target
                    # name. The declared rename wins: drop the occupant
                    # first (its data is intentionally replaced), then
                    # rename. The DROP leads and shows in the preview,
                    # so the destructive replace is reviewed like any
                    # other change.
                    statements.append(
                        self._ddl_statement_builder.build_drop_column_statement(
                            schema_name=self._deploy_schema,
                            table_name=structure.name,
                            column_name=directive.to,
                        ),
                    )
                statements.append(
                    self._ddl_statement_builder.build_rename_column_statement(
                        schema_name=self._deploy_schema,
                        table_name=structure.name,
                        from_name=directive.from_name,
                        to_name=directive.to,
                    ),
                )
                adjusted = self._apply_rename_in_memory(
                    current=adjusted,
                    from_name=directive.from_name,
                    to_name=directive.to,
                )
                outcomes[outcome_key] = (
                    f"renamed (replaced pre-existing '{directive.to}')"
                    if has_to
                    else "renamed"
                )
            elif has_to:
                outcomes[outcome_key] = "no-op (already effective)"
            else:
                raise ChangeFileError(
                    f"Cannot apply {outcome_key}: neither column exists on "
                    f"'{self._deploy_schema}.{structure.name}'.",
                )

        return FieldRenameResolution(
            current=adjusted,
            outcomes=outcomes,
            statements=statements,
        )

    @staticmethod
    def _apply_rename_in_memory(
        current: Structure,
        from_name: str,
        to_name: str,
    ) -> Structure:
        """Return a copy of the live structure with the rename applied.

        When the target name is already held by a different column, that
        occupant is dropped so the renamed column takes its place.
        """
        adjusted = current.model_copy(deep=True)
        adjusted.fields.pop(to_name, None)
        renamed_field = adjusted.fields.pop(from_name)
        adjusted.fields[to_name] = renamed_field.model_copy(
            update={"name": to_name},
        )
        return adjusted
