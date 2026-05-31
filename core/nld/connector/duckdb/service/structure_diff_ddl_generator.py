from nld.connector.duckdb.constants import DUCKDB_DIALECT
from nld.connector.duckdb.sqlglot.ddl import DuckDBSqlglotDDLBuilder
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


class DuckDBStructureDiffDDLGenerator(BaseStructureDiffDDLGenerator):
    """Generates DuckDB-specific DDL from structure diffs."""

    @property
    def dialect(self) -> str:
        """The sqlglot dialect name for SQL rendering."""
        return DUCKDB_DIALECT

    @property
    def _ddl_builder(self) -> DuckDBSqlglotDDLBuilder:
        """Return the DuckDB-specific DDL builder.

        Overrides the base property to use DuckDBSqlglotDDLBuilder
        which bypasses sqlglot's VARCHAR → TEXT normalization.
        """
        return DuckDBSqlglotDDLBuilder()

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

        primary_key_fields = self._get_primary_key_field_names(structure=structure)

        # DuckDB ignores user-supplied PK constraint names and
        # auto-generates <table>_<col>_pkey.  Passing a name would
        # cause a false diff on every deploy cycle because the
        # reader returns the auto-generated name.
        sql = self._ddl_builder.build_create_table(
            schema=schema_name,
            table=structure.name,
            columns=columns,
            primary_key_fields=primary_key_fields,
            primary_key_name=None,
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
                # DuckDB does not support ALTER TABLE ADD CONSTRAINT UNIQUE.
                # Use CREATE UNIQUE INDEX instead.
                statements.append(
                    DDLStatement(
                        sql=self._ddl_builder.build_create_index(
                            index_name=char.name,
                            schema=schema_name,
                            table=structure.name,
                            columns=char.linked_fields or [],
                            unique=True,
                        ),
                        description=f"Create unique index {char.name}",
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

    @staticmethod
    def _is_unbounded_string_type(data_type: str) -> bool:
        """Check if a type is a DuckDB string type with no length.

        DuckDB ignores length limits on string types and
        information_schema never reports them back.  Emitting
        them in DDL would cause a false diff every deploy cycle.
        """
        return data_type.upper() in ("VARCHAR", "TEXT", "CHARACTER VARYING")

    @classmethod
    def _normalize_string_type(cls, data_type: str) -> str:
        """Normalize TEXT and CHARACTER VARYING to VARCHAR.

        The structure reader always returns VARCHAR for all string
        types.  The DDL generator must emit VARCHAR too, otherwise
        a YAML structure with ``data_type: TEXT`` would cause a
        perpetual diff on every deploy cycle (desired=TEXT vs
        current=VARCHAR).
        """
        if cls._is_unbounded_string_type(data_type):
            return "VARCHAR"
        return data_type

    def _build_type_expression(self, field: Field) -> str:
        """Build the type expression including length and precision."""
        data_type: str = field.data_type.upper()
        if self._is_unbounded_string_type(data_type):
            return self._normalize_string_type(data_type)
        if field.length > 0 and field.precision > 0:
            return f"{data_type}({field.length}, {field.precision})"
        if field.length > 0:
            return f"{data_type}({field.length})"
        return data_type

    def _get_primary_key_field_names(self, structure: Structure) -> list[str] | None:
        if not structure.has_primary_key():
            return None
        return [field.name for field in structure.get_primary_key_fields()]

    def _get_primary_key_constraint_name(self, structure: Structure) -> str | None:
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
            # DuckDB does not support ADD COLUMN with NOT NULL inline.
            # Add the column as nullable first, then SET NOT NULL.
            type_expr: str = (
                self._resolve_type_expression(field_diff=field_diff)
                or field_diff.data_type_to
                or "VARCHAR"
            )
            statements.append(
                DDLStatement(
                    sql=self._ddl_builder.build_alter_add_column(
                        schema=schema_name,
                        table=table_name,
                        column_name=field_diff.field_name,
                        data_type=type_expr,
                        not_null=False,
                    ),
                    description=f"Add column {field_diff.field_name}",
                )
            )
            if field_diff.nullable_to is False:
                statements.append(
                    DDLStatement(
                        sql=self._ddl_builder.build_alter_set_not_null(
                            schema=schema_name,
                            table=table_name,
                            column_name=field_diff.field_name,
                        ),
                        description=(f"Make {field_diff.field_name} not nullable"),
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
            modify_type = self._resolve_type_expression(field_diff=field_diff)
            if modify_type is not None:
                statements.append(
                    DDLStatement(
                        sql=self._ddl_builder.build_alter_column_type(
                            schema=schema_name,
                            table=table_name,
                            column_name=field_diff.field_name,
                            new_type=modify_type,
                        ),
                        description=(
                            f"Change type of {field_diff.field_name} "
                            f"from {field_diff.data_type_from} "
                            f"to {modify_type}"
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
            if self._is_unbounded_string_type(field_diff.data_type_to):
                return self._normalize_string_type(field_diff.data_type_to)
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
            data_type = field_diff.data_type_from or "VARCHAR"
            if self._is_unbounded_string_type(data_type):
                return self._normalize_string_type(data_type)
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
            if length > 0 and precision > 0:
                return f"{data_type}({length}, {precision})"
            if length > 0:
                return f"{data_type}({length})"
            return data_type

        return None

    def _generate_characterisation_alter(
        self,
        char_diff: CharacterisationDiff,
        schema_name: str,
        table_name: str,
    ) -> list[DDLStatement]:
        """Generate ALTER statements for a characterisation change.

        DuckDB does not support ALTER TABLE ADD/DROP CONSTRAINT for UNIQUE.
        Both INDEX and UNIQUE characterisations are handled via
        CREATE/DROP INDEX statements.
        """
        if char_diff.characterisation_type in (
            StructureCharacterisationDefinitionNames.INDEX,
            StructureCharacterisationDefinitionNames.UNIQUE,
        ):
            is_unique = (
                char_diff.characterisation_type
                == StructureCharacterisationDefinitionNames.UNIQUE
            )
            return self._generate_index_alter(
                char_diff=char_diff,
                schema_name=schema_name,
                table_name=table_name,
                unique=is_unique,
            )

        # PRIMARY KEY constraints: DuckDB supports ADD CONSTRAINT PK
        # but does NOT support DROP CONSTRAINT.
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

        elif char_diff.action in (DiffAction.DROP, DiffAction.MODIFY):
            raise NotImplementedError(
                f"DuckDB does not support DROP CONSTRAINT. "
                f"Cannot {char_diff.action.value} "
                f"{constraint_type} constraint "
                f"'{char_diff.constraint_name}' on "
                f"'{schema_name}.{table_name}'. "
                f"The table must be recreated to change "
                f"the primary key."
            )

        return statements

    def _generate_index_alter(
        self,
        char_diff: CharacterisationDiff,
        schema_name: str,
        table_name: str,
        unique: bool = False,
    ) -> list[DDLStatement]:
        """Generate DDL for an INDEX or UNIQUE characterisation change.

        DuckDB uses CREATE INDEX / DROP INDEX for both regular and
        unique indexes (no ALTER TABLE ADD/DROP CONSTRAINT support).
        """
        statements: list[DDLStatement] = []
        kind = "unique index" if unique else "index"

        if char_diff.action == DiffAction.ADD:
            statements.append(
                DDLStatement(
                    sql=self._ddl_builder.build_create_index(
                        index_name=char_diff.constraint_name,
                        schema=schema_name,
                        table=table_name,
                        columns=char_diff.linked_fields_to or [],
                        unique=unique,
                    ),
                    description=f"Create {kind} {char_diff.constraint_name}",
                )
            )

        elif char_diff.action == DiffAction.DROP:
            statements.append(
                DDLStatement(
                    sql=self._ddl_builder.build_drop_index(
                        schema=schema_name,
                        index_name=char_diff.constraint_name,
                    ),
                    description=f"Drop {kind} {char_diff.constraint_name}",
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
                        f"Drop {kind} {char_diff.constraint_name} before re-creating"
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
                        unique=unique,
                    ),
                    description=f"Re-create {kind} {char_diff.constraint_name}",
                )
            )

        return statements

    def _characterisation_to_constraint_type(
        self,
        characterisation_type: str,
    ) -> str:
        """Map a characterisation type to a DuckDB constraint keyword."""
        if (
            characterisation_type
            == StructureCharacterisationDefinitionNames.PRIMARY_KEY
        ):
            return "PRIMARY KEY"
        return "UNIQUE"
