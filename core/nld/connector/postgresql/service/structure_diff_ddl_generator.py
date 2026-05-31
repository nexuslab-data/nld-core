from nld.structure.deploy.structure_diff import (
    CharacterisationDiff,
    DiffAction,
    FieldDiff,
    StructureDiff,
)
from nld.structure.deploy.structure_diff_ddl_generator import (
    BaseStructureDiffDDLGenerator,
    DDLStatement,
)
from nld.structure.field.field import Field
from nld.structure.structure.structure import Structure
from nld.structure.structure.structure_characterisation_def import (
    StructureCharacterisationDefinitionNames,
)

POSTGRES_DIALECT = "postgres"


class PostgreSQLStructureDiffDDLGenerator(BaseStructureDiffDDLGenerator):
    """Generates PostgreSQL-specific DDL from structure diffs."""

    @property
    def dialect(self) -> str:
        """The sqlglot dialect name for SQL rendering."""
        return POSTGRES_DIALECT

    def generate_create_table(
        self,
        structure: Structure,
        schema_name: str,
    ) -> list[DDLStatement]:
        """Generate a CREATE TABLE statement."""
        columns = [
            (
                field.name,
                self._build_type_expression(field=field),
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

        for char in structure.characterisations:
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

    def generate_alter_statements(
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

    def _build_type_expression(self, field: Field) -> str:
        """Build the type expression including length and precision."""
        data_type: str = field.data_type.upper()
        if field.length > 0 and field.precision > 0:
            return f"{data_type}({field.length}, {field.precision})"
        if field.length > 0:
            return f"{data_type}({field.length})"
        return data_type

    def _get_primary_key_field_names(
        self,
        structure: Structure,
    ) -> list[str] | None:
        """Get primary key field names if a primary key exists."""
        if not structure.has_primary_key():
            return None
        return [field.name for field in structure.get_primary_key_fields()]

    def _get_primary_key_constraint_name(
        self,
        structure: Structure,
    ) -> str | None:
        """Get primary key constraint name if a named PK characterisation exists."""
        pk_char = structure.get_characterisation(
            StructureCharacterisationDefinitionNames.PRIMARY_KEY,
        )
        if pk_char is None:
            return None
        return pk_char.name

    def _generate_field_alter(
        self,
        field_diff: FieldDiff,
        schema_name: str,
        table_name: str,
    ) -> list[DDLStatement]:
        """Generate ALTER statements for a single field diff."""
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

        return statements

    def _resolve_type_expression(self, field_diff: FieldDiff) -> str | None:
        """Resolve the target type expression from a field diff."""
        if field_diff.data_type_to is not None:
            if (
                field_diff.length_to is not None
                and field_diff.length_to > 0
                and field_diff.precision_to is not None
                and field_diff.precision_to > 0
            ):
                return (
                    f"{field_diff.data_type_to}"
                    f"({field_diff.length_to}, {field_diff.precision_to})"
                )
            if field_diff.length_to is not None and field_diff.length_to > 0:
                return f"{field_diff.data_type_to}({field_diff.length_to})"
            return field_diff.data_type_to

        if field_diff.length_to is not None or field_diff.precision_to is not None:
            length = (
                field_diff.length_to
                if field_diff.length_to is not None
                else field_diff.length_from or 0
            )
            precision = (
                field_diff.precision_to
                if field_diff.precision_to is not None
                else field_diff.precision_from or 0
            )
            data_type = field_diff.data_type_from or "TEXT"
            if length > 0 and precision > 0:
                return f"{data_type}({length}, {precision})"
            if length > 0:
                return f"{data_type}({length})"
            return data_type

        return None

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

    def _characterisation_to_constraint_type(
        self,
        characterisation_type: str,
    ) -> str:
        """Map a characterisation type to a PostgreSQL constraint keyword."""
        if (
            characterisation_type
            == StructureCharacterisationDefinitionNames.PRIMARY_KEY
        ):
            return "PRIMARY KEY"
        return "UNIQUE"
