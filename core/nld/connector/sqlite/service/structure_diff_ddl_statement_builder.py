from nld.connector.sqlite.constants import SQLITE_SCHEMA
from nld.connector.sqlite.service.deploy_capabilities import (
    SQLITE_DEPLOY_CAPABILITIES,
)
from nld.connector.sqlite.sqlglot.ddl import SQLiteSqlglotDDLBuilder
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


class SQLiteStructureDiffDDLStatementBuilder(BaseStructureDiffDDLStatementBuilder):
    """Generates SQLite-specific DDL from structure diffs.

    SQLite's ALTER TABLE adds, renames and drops columns and nothing else,
    so this builder emits those three statements in place and leaves every
    other field change to the rebuild strategy the deploy capabilities ask
    for. Indexes and unique constraints are CREATE/DROP INDEX, the only form
    SQLite has for either.
    """

    @property
    def dialect(self) -> str:
        """The sqlglot dialect name for SQL rendering."""
        return SQLITE_DEPLOY_CAPABILITIES.dialect

    @property
    def _ddl_builder(self) -> SQLiteSqlglotDDLBuilder:
        """Return the SQLite-specific DDL builder."""
        return SQLiteSqlglotDDLBuilder()

    def quote_identifier(self, name: str) -> str:
        """Quote an identifier, the way every other SQLite statement does."""
        return f'"{name}"'

    def _quote_object_path(self, schema_name: str, object_name: str) -> str:
        """Render an object path in the single SQLite namespace."""
        return (
            f"{self.quote_identifier(SQLITE_SCHEMA)}."
            f"{self.quote_identifier(object_name)}"
        )

    def build_release_constraint_statement(
        self,
        schema_name: str,
        table_name: str,
        constraint_name: str,
    ) -> DDLStatement:
        """Release a constraint name held by the archived table.

        SQLite has no ALTER TABLE DROP CONSTRAINT. Every comparable
        characterisation it can carry is backed by an index whose name is
        unique across the database, so the rebuild frees the name by
        dropping the index the archived copy still holds.
        """
        return DDLStatement(
            sql=self._ddl_builder.build_drop_index(
                schema=schema_name,
                index_name=constraint_name,
            ),
            description=(
                f"Release index {constraint_name} from {schema_name}.{table_name}"
            ),
        )

    def build_create_table_statements(
        self,
        structure: Structure,
        schema_name: str,
    ) -> list[DDLStatement]:
        """Generate a CREATE TABLE statement and its indexes."""
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

        column_defaults = {
            field.name: str(field.default_value)
            for field in structure.get_all_fields()
            if field.default_value is not None
        }

        sql = self._ddl_builder.build_create_table(
            schema=schema_name,
            table=structure.name,
            columns=columns,
            primary_key_fields=self._get_primary_key_field_names(structure=structure),
            primary_key_name=None,
            column_defaults=column_defaults,
        )

        table_path = f"{schema_name}.{structure.name}"
        statements = [
            DDLStatement(
                sql=sql,
                description=f"Create table {table_path}",
            )
        ]

        for characterisation in structure.get_deployable_characterisations():
            if characterisation.characterisation not in (
                StructureCharacterisationDefinitionNames.INDEX,
                StructureCharacterisationDefinitionNames.UNIQUE,
            ):
                continue
            is_unique = (
                characterisation.characterisation
                == StructureCharacterisationDefinitionNames.UNIQUE
            )
            statements.append(
                DDLStatement(
                    sql=self._ddl_builder.build_create_index(
                        index_name=characterisation.name,
                        schema=schema_name,
                        table=structure.name,
                        columns=characterisation.linked_fields or [],
                        unique=is_unique,
                    ),
                    description=(
                        f"Create {'unique index' if is_unique else 'index'} "
                        f"{characterisation.name}"
                    ),
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

        for characterisation_diff in diff.characterisation_diffs:
            statements.extend(
                self._generate_characterisation_alter(
                    char_diff=characterisation_diff,
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
        if field_diff.action == DiffAction.ADD:
            return [
                DDLStatement(
                    sql=self._ddl_builder.build_alter_add_column(
                        schema=schema_name,
                        table=table_name,
                        column_name=field_diff.field_name,
                        data_type=(
                            self._resolve_type_expression(field_diff=field_diff)
                            or field_diff.data_type_to
                            or "TEXT"
                        ),
                        # SQLite refuses NOT NULL without a default on ADD
                        # COLUMN: a mandatory new column lands through the
                        # rebuild instead.
                        not_null=False,
                        default_value=field_diff.default_to,
                    ),
                    description=f"Add column {field_diff.field_name}",
                )
            ]

        if field_diff.action == DiffAction.DROP:
            return [
                DDLStatement(
                    sql=self._ddl_builder.build_alter_drop_column(
                        schema=schema_name,
                        table=table_name,
                        column_name=field_diff.field_name,
                    ),
                    description=f"Drop column {field_diff.field_name}",
                )
            ]

        # A MODIFY reaches here only when the deploy did not route the
        # structure through a rebuild, which its capabilities say it must.
        raise NotImplementedError(
            f"SQLite cannot modify the column '{field_diff.field_name}' of "
            f"'{schema_name}.{table_name}' in place. The table must be "
            f"rebuilt."
        )

    def _generate_characterisation_alter(
        self,
        char_diff: CharacterisationDiff,
        schema_name: str,
        table_name: str,
    ) -> list[DDLStatement]:
        """Generate DDL for a characterisation change.

        Indexes and unique constraints are both CREATE/DROP INDEX. A primary
        key change is impossible in place: SQLite has no ALTER TABLE ADD or
        DROP CONSTRAINT, so the table has to be rebuilt.
        """
        if char_diff.characterisation_type not in (
            StructureCharacterisationDefinitionNames.INDEX,
            StructureCharacterisationDefinitionNames.UNIQUE,
        ):
            raise NotImplementedError(
                f"SQLite cannot {char_diff.action.value} the "
                f"{char_diff.characterisation_type} constraint "
                f"'{char_diff.constraint_name}' on "
                f"'{schema_name}.{table_name}' in place. The table must be "
                f"rebuilt (nld structure deploy --rebuild)."
            )

        is_unique = (
            char_diff.characterisation_type
            == StructureCharacterisationDefinitionNames.UNIQUE
        )
        kind = "unique index" if is_unique else "index"
        statements: list[DDLStatement] = []

        if char_diff.action in (DiffAction.DROP, DiffAction.MODIFY):
            statements.append(
                DDLStatement(
                    sql=self._ddl_builder.build_drop_index(
                        schema=schema_name,
                        index_name=char_diff.constraint_name,
                    ),
                    description=f"Drop {kind} {char_diff.constraint_name}",
                )
            )

        if char_diff.action in (DiffAction.ADD, DiffAction.MODIFY):
            statements.append(
                DDLStatement(
                    sql=self._ddl_builder.build_create_index(
                        index_name=char_diff.constraint_name,
                        schema=schema_name,
                        table=table_name,
                        columns=char_diff.linked_fields_to or [],
                        unique=is_unique,
                    ),
                    description=f"Create {kind} {char_diff.constraint_name}",
                )
            )

        return statements
