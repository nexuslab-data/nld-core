from __future__ import annotations

from nld.connector.base.deploy_capabilities import ConnectorDeployCapabilities
from nld.structure.deploy.structure_diff import (
    CharacterisationDiff,
    DiffAction,
    StructureDiff,
)
from nld.structure.deploy.structure_diff_ddl_statement_builder import (
    BaseStructureDiffDDLStatementBuilder,
    DDLStatement,
)
from nld.structure.structure.structure import Structure


class RebuildStrategyBuilder:
    """Builds the statement sequences of the two REBUILD strategies.

    The backup strategy rebuilds a live table in place — new copy
    built and loaded first, old table archived, copy promoted — while
    the drop-and-recreate strategy of ``--rebuild`` ignores current
    state entirely.
    """

    def __init__(
        self,
        ddl_statement_builder: BaseStructureDiffDDLStatementBuilder,
        capabilities: ConnectorDeployCapabilities,
        deploy_schema: str,
        backup_suffix: str,
    ) -> None:
        self._ddl_statement_builder = ddl_statement_builder
        self._capabilities = capabilities
        self._deploy_schema = deploy_schema
        self._backup_suffix = backup_suffix

    def build_backup_statements(
        self,
        structure: Structure,
        current: Structure,
    ) -> list[DDLStatement]:
        """Build the backup-create-reinsert statements of the REBUILD strategy.

        Fail-safe ordering: the new table is fully built and loaded
        before the old one moves, so a failure before the swap leaves
        the original serving, and a leftover working copy is dropped
        on the next attempt. The swap itself runs atomically on
        engines with transactional DDL (PostgreSQL); elsewhere a crash
        between its statements can leave the archived copy as the only
        table. The old table is archived (retained) as
        ``<name>__nld_backup_<ts>``, never dropped. Comparable
        structure characterisations are re-added on the swapped-in
        table from the desired definition.
        """
        new_table_name = f"{structure.name}__nld_new"
        backup_table_name = f"{structure.name}__nld_backup_{self._backup_suffix}"

        # A crashed earlier rebuild can leave a stale working copy
        # behind; it was never promoted, so dropping it is safe and
        # makes the rebuild re-runnable.
        statements = [
            DDLStatement(
                sql=self._ddl_statement_builder.build_drop_table_statement(
                    schema_name=self._deploy_schema,
                    table_name=new_table_name,
                ).sql,
                description=(
                    f"Drop a leftover {new_table_name} from a previously "
                    "interrupted rebuild"
                ),
            ),
        ]

        # Constraints are re-added after the swap under their real
        # names: the temporary table must carry none — a field-level
        # unique would otherwise expand under the temporary name and
        # survive the swap as a stale constraint.
        bare_fields = {
            field_name: field.model_copy(
                update={
                    "characterisations": [
                        field_characterisation
                        for field_characterisation in field.characterisations
                        if field_characterisation.characterisation != "unique"
                    ],
                },
            )
            for field_name, field in structure.fields.items()
        }
        bare_structure = structure.model_copy(
            update={
                "characterisations": [],
                "fields": bare_fields,
                "name": new_table_name,
            },
        )
        statements.extend(
            self._ddl_statement_builder.build_create_table_statements(
                structure=bare_structure,
                schema_name=self._deploy_schema,
            ),
        )

        desired_fields = {field.name: field for field in structure.get_all_fields()}
        desired_order = list(desired_fields.keys())
        current_names = {field.name for field in current.get_all_fields()}
        copied_names = [name for name in desired_order if name in current_names]
        copied_columns = ", ".join(copied_names)
        # The old table's live types can differ from the declared ones
        # (the rebuild often exists to fix exactly that), so every
        # copied column casts explicitly to its target type.
        select_columns = ", ".join(
            self._ddl_statement_builder.build_cast_expression(
                column_name=name,
                field=desired_fields[name],
            )
            for name in copied_names
        )
        statements.append(
            DDLStatement(
                sql=(
                    f"INSERT INTO {self._deploy_schema}.{new_table_name} "
                    f"({copied_columns}) SELECT {select_columns} "
                    f"FROM {self._deploy_schema}.{structure.name}"
                ),
                description=(
                    f"Copy data into the rebuilt {structure.name} "
                    "in the desired column order, cast to the "
                    "declared target types"
                ),
            ),
        )
        # Constraint names follow the table rename but their backing
        # indexes stay schema-unique: the archived copy must release
        # them before the swapped-in table re-adds the same names.
        comparable_types = set(self._capabilities.comparable_characterisations)
        release_constraint_names = [
            old_characterisation.name
            for old_characterisation in current.characterisations
            if old_characterisation.characterisation in comparable_types
        ]
        statements.extend(
            self._ddl_statement_builder.build_table_swap_statements(
                schema_name=self._deploy_schema,
                table_name=structure.name,
                backup_table_name=backup_table_name,
                new_table_name=new_table_name,
                release_constraint_names=release_constraint_names,
            ),
        )
        constraint_diffs = [
            CharacterisationDiff(
                action=DiffAction.ADD,
                characterisation_type=characterisation.characterisation,
                constraint_name=characterisation.name,
                linked_fields_to=characterisation.linked_fields,
            )
            for characterisation in structure.get_deployable_characterisations()
            if characterisation.characterisation in comparable_types
        ]
        if constraint_diffs:
            statements.extend(
                self._ddl_statement_builder.build_alter_statements(
                    diff=StructureDiff(
                        structure_name=structure.name,
                        table_exists=True,
                        characterisation_diffs=constraint_diffs,
                    ),
                    schema_name=self._deploy_schema,
                ),
            )
        return statements

    def build_drop_and_recreate_statements(
        self,
        structure: Structure,
    ) -> list[DDLStatement]:
        """Compute the drop-and-recreate statements of the rebuild mode."""
        return [
            self._ddl_statement_builder.build_drop_table_statement(
                schema_name=self._deploy_schema,
                table_name=structure.name,
            ),
        ] + self._ddl_statement_builder.build_create_table_statements(
            structure=structure,
            schema_name=self._deploy_schema,
        )
