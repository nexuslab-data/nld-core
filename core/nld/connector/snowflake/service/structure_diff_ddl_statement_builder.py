from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nld.connector.snowflake.sqlglot import SnowflakeSqlglotDDLBuilder

from nld.connector.snowflake.service.deploy_capabilities import (
    SNOWFLAKE_DEPLOY_CAPABILITIES,
)
from nld.structure.deploy.structure_diff import (
    CharacterisationDiff,
    DiffAction,
    FieldDiff,
    StructureDiff,
)
from nld.structure.deploy.structure_diff_ddl_statement_builder import (
    BaseStructureDiffDDLStatementBuilder,
    DDLStatement,
)
from nld.structure.structure.structure import Structure
from nld.structure.structure.structure_characterisation_def import (
    StructureCharacterisationDefinitionNames,
)


class SnowflakeStructureDiffDDLStatementBuilder(BaseStructureDiffDDLStatementBuilder):
    """Generates Snowflake-specific DDL from structure diffs."""

    @property
    def dialect(self) -> str:
        return SNOWFLAKE_DEPLOY_CAPABILITIES.dialect

    @property
    def _ddl_builder(self) -> SnowflakeSqlglotDDLBuilder:
        from nld.connector.snowflake.sqlglot import SnowflakeSqlglotDDLBuilder

        return SnowflakeSqlglotDDLBuilder()

    def build_create_table_statements(
        self,
        structure: Structure,
        schema_name: str,
    ) -> list[DDLStatement]:
        columns = [
            (
                field.name,
                self._ddl_builder.build_type_expression(
                    data_type=field.data_type,
                    length=field.length,
                    precision=field.precision,
                ),
                field.is_mandatory(),
            )
            for field in structure.get_all_fields()
        ]

        primary_key_fields = self._get_primary_key_field_names(structure)
        primary_key_name = self._get_primary_key_constraint_name(structure)
        column_defaults = {
            field.name: str(field.default_value)
            for field in structure.get_all_fields()
            if field.default_value is not None
        }

        sql = self._ddl_builder.build_create_table(
            schema=schema_name,
            table=structure.name,
            columns=columns,
            primary_key_fields=primary_key_fields,
            primary_key_name=primary_key_name,
            column_defaults=column_defaults or None,
        )

        table_path = f"{schema_name}.{structure.name}"
        statements = [
            DDLStatement(
                sql=sql,
                description=f"Create table {table_path}",
            )
        ]

        for char in structure.get_deployable_characterisations():
            if char.characterisation == StructureCharacterisationDefinitionNames.UNIQUE:
                statements.append(
                    DDLStatement(
                        sql=self._ddl_builder.build_alter_add_constraint(
                            schema=schema_name,
                            table=structure.name,
                            constraint_name=char.name,
                            constraint_type="UNIQUE",
                            columns=char.linked_fields or [],
                        ),
                        description=f"Add unique constraint {char.name}",
                    )
                )

        return statements

    def build_release_constraint_statement(
        self,
        schema_name: str,
        table_name: str,
        constraint_name: str,
    ) -> DDLStatement:
        """Generate a constraint drop for the rebuild swap.

        Snowflake does not accept ``IF EXISTS`` on ``DROP
        CONSTRAINT``; the released constraints come from the live
        read-back state, so they exist by construction.
        """
        return DDLStatement(
            sql=(
                f"ALTER TABLE {schema_name}.{table_name} "
                f"DROP CONSTRAINT {constraint_name}"
            ),
            description=(
                f"Release constraint {constraint_name} from {schema_name}.{table_name}"
            ),
        )

    def build_rename_table_statement(
        self,
        schema_name: str,
        from_name: str,
        to_name: str,
    ) -> DDLStatement:
        """Generate a Snowflake table rename statement.

        Snowflake resolves an unqualified ``RENAME TO`` target against
        the session's current schema — not the schema of the renamed
        table — so the new name must be schema-qualified to keep the
        table in place.
        """
        return DDLStatement(
            sql=(
                f"ALTER TABLE {schema_name}.{from_name} "
                f"RENAME TO {schema_name}.{to_name}"
            ),
            description=(f"Rename table {schema_name}.{from_name} to {to_name}"),
        )

    def build_alter_statements(
        self,
        diff: StructureDiff,
        schema_name: str,
    ) -> list[DDLStatement]:
        statements: list[DDLStatement] = []

        for field_diff in diff.field_diffs:
            statements.extend(
                self._generate_field_alter(
                    field_diff=field_diff,
                    schema_name=schema_name,
                    table_name=diff.structure_name,
                )
            )

        # Drops lead: Snowflake refuses a constraint whose signature
        # (type + column set) already exists on the table, so an old
        # constraint must release its signature before the renamed
        # replacement is added.
        ordered_char_diffs = sorted(
            diff.characterisation_diffs,
            key=lambda char_diff: char_diff.action != DiffAction.DROP,
        )
        for char_diff in ordered_char_diffs:
            statements.extend(
                self._generate_characterisation_alter(
                    char_diff=char_diff,
                    schema_name=schema_name,
                    table_name=diff.structure_name,
                )
            )

        return statements

    def _generate_field_alter(
        self,
        field_diff: FieldDiff,
        schema_name: str,
        table_name: str,
    ) -> list[DDLStatement]:
        statements: list[DDLStatement] = []

        if field_diff.action == DiffAction.ADD:
            statements.append(
                DDLStatement(
                    sql=self._ddl_builder.build_alter_add_column(
                        schema=schema_name,
                        table=table_name,
                        column_name=field_diff.field_name,
                        data_type=field_diff.data_type_to or "TEXT",
                        not_null=field_diff.nullable_to is False,
                        default_value=field_diff.default_to,
                    ),
                    description=f"Add column {field_diff.field_name}",
                )
            )

        elif field_diff.action == DiffAction.DROP:
            statements.append(
                DDLStatement(
                    sql=self._ddl_builder.build_alter_drop_column(
                        schema=schema_name,
                        table=table_name,
                        column_name=field_diff.field_name,
                    ),
                    description=f"Drop column {field_diff.field_name}",
                )
            )

        elif field_diff.action == DiffAction.MODIFY:
            # No default handling here: Snowflake cannot SET DEFAULT
            # on an existing column, so the deploy manager routes
            # default modifications to the REBUILD strategy
            # (alter_column_set_default=False in the capabilities).
            type_expr = self._resolve_type_expression(field_diff)
            if type_expr is not None:
                statements.append(
                    DDLStatement(
                        sql=self._ddl_builder.build_alter_column_type(
                            schema=schema_name,
                            table=table_name,
                            column_name=field_diff.field_name,
                            new_type=type_expr,
                        ),
                        description=(
                            f"Change type of {field_diff.field_name} "
                            f"from {field_diff.data_type_from} to {type_expr}"
                        ),
                    )
                )

            if field_diff.nullable_to is not None:
                if field_diff.nullable_to:
                    statements.append(
                        DDLStatement(
                            sql=self._ddl_builder.build_alter_drop_not_null(
                                schema=schema_name,
                                table=table_name,
                                column_name=field_diff.field_name,
                            ),
                            description=f"Make {field_diff.field_name} nullable",
                        )
                    )
                else:
                    statements.append(
                        DDLStatement(
                            sql=self._ddl_builder.build_alter_set_not_null(
                                schema=schema_name,
                                table=table_name,
                                column_name=field_diff.field_name,
                            ),
                            description=f"Make {field_diff.field_name} not nullable",
                        )
                    )

        return statements

    def _generate_characterisation_alter(
        self,
        char_diff: CharacterisationDiff,
        schema_name: str,
        table_name: str,
    ) -> list[DDLStatement]:
        # Snowflake does not support CREATE INDEX
        if (
            char_diff.characterisation_type
            == StructureCharacterisationDefinitionNames.INDEX
        ):
            return []

        statements: list[DDLStatement] = []
        constraint_type = self._characterisation_to_constraint_type(
            char_diff.characterisation_type,
        )

        if char_diff.action == DiffAction.ADD:
            statements.append(
                DDLStatement(
                    sql=self._ddl_builder.build_alter_add_constraint(
                        schema=schema_name,
                        table=table_name,
                        constraint_name=char_diff.constraint_name,
                        constraint_type=constraint_type,
                        columns=char_diff.linked_fields_to or [],
                    ),
                    description=(
                        f"Add {constraint_type} constraint {char_diff.constraint_name}"
                    ),
                )
            )

        elif char_diff.action == DiffAction.DROP:
            statements.append(
                DDLStatement(
                    sql=self._ddl_builder.build_alter_drop_constraint(
                        schema=schema_name,
                        table=table_name,
                        constraint_name=char_diff.constraint_name,
                    ),
                    description=f"Drop constraint {char_diff.constraint_name}",
                )
            )

        elif char_diff.action == DiffAction.MODIFY:
            statements.append(
                DDLStatement(
                    sql=self._ddl_builder.build_alter_drop_constraint(
                        schema=schema_name,
                        table=table_name,
                        constraint_name=char_diff.constraint_name,
                    ),
                    description=(
                        f"Drop constraint {char_diff.constraint_name} "
                        f"before re-creating"
                    ),
                )
            )
            statements.append(
                DDLStatement(
                    sql=self._ddl_builder.build_alter_add_constraint(
                        schema=schema_name,
                        table=table_name,
                        constraint_name=char_diff.constraint_name,
                        constraint_type=constraint_type,
                        columns=char_diff.linked_fields_to or [],
                    ),
                    description=(
                        f"Re-create {constraint_type} constraint "
                        f"{char_diff.constraint_name}"
                    ),
                )
            )

        return statements
