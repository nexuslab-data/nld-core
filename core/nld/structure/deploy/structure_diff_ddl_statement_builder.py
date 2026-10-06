from abc import ABC, abstractmethod

from nld.pydantic.base_model import NldBaseModel
from nld.structure.deploy.structure_diff import FieldDiff, StructureDiff
from nld.structure.field.field import Field
from nld.structure.structure.structure import Structure
from nld.structure.structure.structure_characterisation_def import (
    StructureCharacterisationDefinitionNames,
)
from nld.utils.sqlglot.base_ddl import BaseSqlglotDDLBuilder


class DDLStatement(NldBaseModel):
    """A single DDL statement with a human-readable description."""

    sql: str
    description: str


class BaseStructureDiffDDLStatementBuilder(ABC):
    """Abstract base for generating DDL from structure diffs.

    Subclasses implement database-specific SQL generation for
    CREATE TABLE and ALTER TABLE statements.
    """

    @property
    @abstractmethod
    def dialect(self) -> str:
        """The sqlglot dialect name for SQL rendering."""
        raise NotImplementedError

    @property
    def _ddl_builder(self) -> BaseSqlglotDDLBuilder:
        """Return a DDL builder for this generator's dialect."""
        return BaseSqlglotDDLBuilder(dialect=self.dialect)

    def quote_identifier(self, name: str) -> str:
        """Render an identifier for this dialect's generic statements.

        The default returns the name unchanged: engines whose objects
        are created with unquoted identifiers (Snowflake stores them
        uppercase) must not suddenly reference quoted, case-sensitive
        names. Engines that quote identifiers in their other DDL
        (PostgreSQL) override this so every statement follows one
        quoting discipline.
        """
        return name

    def _quote_object_path(self, schema_name: str, object_name: str) -> str:
        """Render a schema-qualified object path with the dialect quoting."""
        schema = self.quote_identifier(schema_name)
        return f"{schema}.{self.quote_identifier(object_name)}"

    def build_cast_expression(
        self,
        column_name: str,
        field: Field,
    ) -> str:
        """Render a column expression cast to the field's declared type.

        The rebuild copy reads the old table's columns, whose live
        types can differ from the declared ones (e.g. TEXT into an
        INTEGER target): the engine refuses the implicit conversion,
        so every copied column casts explicitly to its target type.
        The type renders through ``build_type_expression`` — the same
        single place the CREATE and ALTER statements render it.
        """
        type_expression = self._ddl_builder.build_type_expression(
            data_type=field.data_type,
            length=field.length,
            precision=field.precision,
        )
        return f"CAST({self.quote_identifier(column_name)} AS {type_expression})"

    def build_copy_rows_statement(
        self,
        schema_name: str,
        source_table_name: str,
        target_table_name: str,
        column_names: list[str],
        select_expressions: list[str],
    ) -> DDLStatement:
        """Generate the INSERT … SELECT that fills a rebuilt table.

        Rendered through the dialect's own object-path and identifier
        quoting so engines whose object paths are not a plain
        ``schema.table`` (SQLite resolves every schema to ``main``) copy
        into a reference the engine accepts.
        """
        target_path = self._quote_object_path(schema_name, target_table_name)
        source_path = self._quote_object_path(schema_name, source_table_name)
        quoted_columns = ", ".join(
            self.quote_identifier(column_name) for column_name in column_names
        )
        return DDLStatement(
            sql=(
                f"INSERT INTO {target_path} ({quoted_columns}) "
                f"SELECT {', '.join(select_expressions)} FROM {source_path}"
            ),
            description=(
                f"Copy data into the rebuilt {source_table_name} "
                "in the desired column order, cast to the "
                "declared target types"
            ),
        )

    @abstractmethod
    def build_create_table_statements(
        self,
        structure: Structure,
        schema_name: str,
    ) -> list[DDLStatement]:
        """Generate CREATE TABLE statements for a new structure."""
        raise NotImplementedError

    @abstractmethod
    def build_alter_statements(
        self,
        diff: StructureDiff,
        schema_name: str,
    ) -> list[DDLStatement]:
        """Generate ALTER TABLE statements for an existing structure."""
        raise NotImplementedError

    def build_rename_column_statement(
        self,
        schema_name: str,
        table_name: str,
        from_name: str,
        to_name: str,
    ) -> DDLStatement:
        """Generate a column rename statement.

        The generic ``ALTER TABLE … RENAME COLUMN`` form works on
        PostgreSQL, Snowflake and DuckDB; dialects that need another
        form override this method.
        """
        return DDLStatement(
            sql=(
                f"ALTER TABLE {self._quote_object_path(schema_name, table_name)} "
                f"RENAME COLUMN {self.quote_identifier(from_name)} "
                f"TO {self.quote_identifier(to_name)}"
            ),
            description=(
                f"Rename column {from_name} to {to_name} on {schema_name}.{table_name}"
            ),
        )

    def build_drop_column_statement(
        self,
        schema_name: str,
        table_name: str,
        column_name: str,
    ) -> DDLStatement:
        """Generate a column drop statement.

        Used by the rename resolver to vacate a name a declared rename
        targets when a different live column already holds it. The
        generic ``ALTER TABLE … DROP COLUMN`` form works on PostgreSQL,
        Snowflake, DuckDB and BigQuery; dialects that need another form
        override this method.
        """
        return DDLStatement(
            sql=(
                f"ALTER TABLE {self._quote_object_path(schema_name, table_name)} "
                f"DROP COLUMN {self.quote_identifier(column_name)}"
            ),
            description=(f"Drop column {column_name} on {schema_name}.{table_name}"),
        )

    def build_rename_table_statement(
        self,
        schema_name: str,
        from_name: str,
        to_name: str,
    ) -> DDLStatement:
        """Generate a table rename statement.

        The generic ``ALTER TABLE … RENAME TO`` form works on
        PostgreSQL, Snowflake and DuckDB; dialects that need another
        form override this method.
        """
        return DDLStatement(
            sql=(
                f"ALTER TABLE {self._quote_object_path(schema_name, from_name)} "
                f"RENAME TO {self.quote_identifier(to_name)}"
            ),
            description=(f"Rename table {schema_name}.{from_name} to {to_name}"),
        )

    def build_release_constraint_statement(
        self,
        schema_name: str,
        table_name: str,
        constraint_name: str,
    ) -> DDLStatement:
        """Generate a defensive constraint drop for the rebuild swap.

        The generic ``DROP CONSTRAINT IF EXISTS`` form works on
        PostgreSQL and DuckDB; dialects without ``IF EXISTS`` support
        override this method.
        """
        return DDLStatement(
            sql=(
                f"ALTER TABLE {self._quote_object_path(schema_name, table_name)} "
                f"DROP CONSTRAINT IF EXISTS {self.quote_identifier(constraint_name)}"
            ),
            description=(
                f"Release constraint {constraint_name} from {schema_name}.{table_name}"
            ),
        )

    def build_table_swap_statements(
        self,
        schema_name: str,
        table_name: str,
        backup_table_name: str,
        new_table_name: str,
        release_constraint_names: list[str],
    ) -> list[DDLStatement]:
        """Generate the rebuild swap: archive the old table, promote the new.

        Sequence: rename ``table_name`` to ``backup_table_name``,
        release the archived copy's comparable constraints (their
        names stay schema-unique and must be freed for the promoted
        table to re-add them), then rename ``new_table_name`` to
        ``table_name``. Engines with transactional DDL override this
        to run the whole swap atomically — the default per-statement
        form has a no-table window between the two renames.
        """
        statements = [
            self.build_rename_table_statement(
                schema_name=schema_name,
                from_name=table_name,
                to_name=backup_table_name,
            ),
        ]
        statements.extend(
            self.build_release_constraint_statement(
                schema_name=schema_name,
                table_name=backup_table_name,
                constraint_name=constraint_name,
            )
            for constraint_name in release_constraint_names
        )
        statements.append(
            self.build_rename_table_statement(
                schema_name=schema_name,
                from_name=new_table_name,
                to_name=table_name,
            ),
        )
        return statements

    def build_drop_view_statement(
        self,
        schema_name: str,
        view_name: str,
    ) -> DDLStatement:
        """Generate a view drop statement for dependent-view handling."""
        return DDLStatement(
            sql=(
                f"DROP VIEW IF EXISTS {self._quote_object_path(schema_name, view_name)}"
            ),
            description=f"Drop dependent view {schema_name}.{view_name}",
        )

    def build_drop_table_statement(
        self,
        schema_name: str,
        table_name: str,
    ) -> DDLStatement:
        """Generate a table drop statement for the rebuild mode.

        No CASCADE: a dependent view must fail the drop loudly, never
        be destroyed silently.
        """
        return DDLStatement(
            sql=(
                "DROP TABLE IF EXISTS "
                f"{self._quote_object_path(schema_name, table_name)}"
            ),
            description=f"Drop table {schema_name}.{table_name}",
        )

    # Fallback data type when a length/precision-only change carries
    # no explicit type; engines with another canonical string type
    # override the attribute (BigQuery: STRING).
    _TYPE_CHANGE_FALLBACK_DATA_TYPE = "TEXT"

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
            data_type = (
                field_diff.data_type_from or self._TYPE_CHANGE_FALLBACK_DATA_TYPE
            )
            if length > 0 and precision > 0:
                return f"{data_type}({length}, {precision})"
            if length > 0:
                return f"{data_type}({length})"
            return data_type

        return None

    def _characterisation_to_constraint_type(
        self,
        characterisation_type: str,
    ) -> str:
        """Map a characterisation type to the engine's constraint keyword."""
        if (
            characterisation_type
            == StructureCharacterisationDefinitionNames.PRIMARY_KEY
        ):
            return "PRIMARY KEY"
        return "UNIQUE"

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

    def build_ddl_statements(
        self,
        diff: StructureDiff,
        structure: Structure,
        schema_name: str,
    ) -> list[DDLStatement]:
        """Dispatch to create or alter based on whether the table exists."""
        if diff.is_new_table():
            return self.build_create_table_statements(
                structure=structure,
                schema_name=schema_name,
            )
        return self.build_alter_statements(
            diff=diff,
            schema_name=schema_name,
        )
