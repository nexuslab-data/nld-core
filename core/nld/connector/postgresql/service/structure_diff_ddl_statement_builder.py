from sqlglot import exp

from nld.connector.postgresql.service.deploy_capabilities import (
    POSTGRESQL_DEPLOY_CAPABILITIES,
)
from nld.connector.postgresql.sqlglot.ddl import PostgreSQLSqlglotDDLBuilder
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


class PostgreSQLStructureDiffDDLStatementBuilder(BaseStructureDiffDDLStatementBuilder):
    """Generates PostgreSQL-specific DDL from structure diffs."""

    @property
    def dialect(self) -> str:
        """The sqlglot dialect name for SQL rendering."""
        return POSTGRESQL_DEPLOY_CAPABILITIES.dialect

    @property
    def _ddl_builder(self) -> PostgreSQLSqlglotDDLBuilder:
        """Use the PostgreSQL-specific DDL builder."""
        return PostgreSQLSqlglotDDLBuilder()

    def quote_identifier(self, name: str) -> str:
        """Double-quote, like every other statement this builder emits.

        One quoting discipline for the whole builder: a mixed-case or
        reserved-word identifier must not break the rename path while
        the ADD COLUMN path handles it.
        """
        return exp.to_identifier(name, quoted=True).sql(dialect=self.dialect)

    def build_table_swap_statements(
        self,
        schema_name: str,
        table_name: str,
        backup_table_name: str,
        new_table_name: str,
        release_constraint_names: list[str],
    ) -> list[DDLStatement]:
        """Run the rebuild swap as one atomic statement.

        PostgreSQL supports transactional DDL and the connector
        executes a multi-statement string in a single transaction, so
        the archive rename, constraint releases and promote rename
        either all apply or none do — no crash can leave the schema
        with no serving table.
        """
        per_statement = super().build_table_swap_statements(
            schema_name=schema_name,
            table_name=table_name,
            backup_table_name=backup_table_name,
            new_table_name=new_table_name,
            release_constraint_names=release_constraint_names,
        )
        return [
            DDLStatement(
                sql="; ".join(statement.sql for statement in per_statement),
                description=(
                    f"Atomically swap {schema_name}.{table_name} with its "
                    f"rebuilt copy (archived as {backup_table_name})"
                ),
            ),
        ]

    def build_create_table_statements(
        self,
        structure: Structure,
        schema_name: str,
    ) -> list[DDLStatement]:
        """Generate a CREATE TABLE statement."""
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

        primary_key_fields = self._get_primary_key_field_names(
            structure=structure,
        )
        primary_key_name = self._get_primary_key_constraint_name(
            structure=structure,
        )

        sql = self._ddl_builder.build_create_table(
            schema=schema_name,
            table=structure.name,
            columns=columns,
            primary_key_fields=primary_key_fields,
            primary_key_name=primary_key_name,
        )

        table_path = f"{schema_name}.{structure.name}"
        statements = [
            DDLStatement(
                sql=sql,
                description=f"Create table {table_path}",
            )
        ]

        for field in structure.get_all_fields():
            if field.default_value is None:
                continue
            statements.append(
                DDLStatement(
                    sql=self._ddl_builder.build_alter_set_default(
                        schema=schema_name,
                        table=structure.name,
                        column_name=field.name,
                        default_value=str(field.default_value),
                    ),
                    description=(
                        f"Set default of {field.name} to {field.default_value}"
                    ),
                )
            )

        for char in structure.get_deployable_characterisations():
            if char.characterisation == StructureCharacterisationDefinitionNames.INDEX:
                statements.append(
                    DDLStatement(
                        sql=self._ddl_builder.build_create_index(
                            index_name=char.name,
                            schema=schema_name,
                            table=structure.name,
                            columns=char.linked_fields or [],
                        ),
                        description=f"Create index {char.name}",
                    )
                )
            elif (
                char.characterisation == StructureCharacterisationDefinitionNames.UNIQUE
            ):
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

    def build_alter_statements(
        self,
        diff: StructureDiff,
        schema_name: str,
    ) -> list[DDLStatement]:
        """Generate ALTER TABLE statements from a structure diff."""
        statements: list[DDLStatement] = []

        for field_diff in diff.field_diffs:
            statements.extend(
                self._generate_field_alter(
                    field_diff=field_diff,
                    schema_name=schema_name,
                    table_name=diff.structure_name,
                )
            )

        for char_diff in diff.characterisation_diffs:
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
        """Generate ALTER statements for a single field diff."""
        statements: list[DDLStatement] = []

        if field_diff.action == DiffAction.ADD:
            add_type = self._ddl_builder.build_type_expression(
                data_type=field_diff.data_type_to or "TEXT",
                length=field_diff.length_to or 0,
                precision=field_diff.precision_to or 0,
            )
            statements.append(
                DDLStatement(
                    sql=self._ddl_builder.build_alter_add_column(
                        schema=schema_name,
                        table=table_name,
                        column_name=field_diff.field_name,
                        data_type=add_type,
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
            type_expr = self._resolve_type_expression(field_diff=field_diff)
            if type_expr is not None:
                statements.append(
                    DDLStatement(
                        sql=self._ddl_builder.build_alter_column_type(
                            schema=schema_name,
                            table=table_name,
                            column_name=field_diff.field_name,
                            new_type=type_expr,
                        ),
                        description=self._type_change_description(
                            field_diff=field_diff,
                            type_expr=type_expr,
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

            if field_diff.default_to is not None:
                statements.append(
                    DDLStatement(
                        sql=self._ddl_builder.build_alter_set_default(
                            schema=schema_name,
                            table=table_name,
                            column_name=field_diff.field_name,
                            default_value=field_diff.default_to,
                        ),
                        description=(
                            f"Set default of {field_diff.field_name} "
                            f"to {field_diff.default_to}"
                        ),
                    )
                )

        return statements

    def _type_change_description(
        self,
        field_diff: FieldDiff,
        type_expr: str,
    ) -> str:
        """Build a human-readable description for a type change."""
        if field_diff.data_type_to is not None:
            return (
                f"Change type of {field_diff.field_name} "
                f"from {field_diff.data_type_from} to {type_expr}"
            )
        return f"Change size of {field_diff.field_name} to {type_expr}"

    def _generate_characterisation_alter(
        self,
        char_diff: CharacterisationDiff,
        schema_name: str,
        table_name: str,
    ) -> list[DDLStatement]:
        """Generate ALTER statements for a characterisation change."""
        if (
            char_diff.characterisation_type
            == StructureCharacterisationDefinitionNames.INDEX
        ):
            return self._generate_index_alter(
                char_diff=char_diff,
                schema_name=schema_name,
                table_name=table_name,
            )

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

    def _generate_index_alter(
        self,
        char_diff: CharacterisationDiff,
        schema_name: str,
        table_name: str,
    ) -> list[DDLStatement]:
        """Generate DDL statements for an INDEX characterisation change.

        INDEX uses CREATE INDEX / DROP INDEX syntax instead of
        ALTER TABLE ADD/DROP CONSTRAINT.
        """
        statements: list[DDLStatement] = []

        if char_diff.action == DiffAction.ADD:
            statements.append(
                DDLStatement(
                    sql=self._ddl_builder.build_create_index(
                        index_name=char_diff.constraint_name,
                        schema=schema_name,
                        table=table_name,
                        columns=char_diff.linked_fields_to or [],
                    ),
                    description=f"Create index {char_diff.constraint_name}",
                )
            )

        elif char_diff.action == DiffAction.DROP:
            statements.append(
                DDLStatement(
                    sql=self._ddl_builder.build_drop_index(
                        schema=schema_name,
                        index_name=char_diff.constraint_name,
                    ),
                    description=f"Drop index {char_diff.constraint_name}",
                )
            )

        elif char_diff.action == DiffAction.MODIFY:
            statements.append(
                DDLStatement(
                    sql=self._ddl_builder.build_drop_index(
                        schema=schema_name,
                        index_name=char_diff.constraint_name,
                    ),
                    description=(
                        f"Drop index {char_diff.constraint_name} before re-creating"
                    ),
                )
            )
            statements.append(
                DDLStatement(
                    sql=self._ddl_builder.build_create_index(
                        index_name=char_diff.constraint_name,
                        schema=schema_name,
                        table=table_name,
                        columns=char_diff.linked_fields_to or [],
                    ),
                    description=f"Re-create index {char_diff.constraint_name}",
                )
            )

        return statements
