from sqlglot import exp

from nld.connector.sqlite.constants import SQLITE_DIALECT, SQLITE_SCHEMA
from nld.utils.sqlglot.base_ddl import BaseSqlglotDDLBuilder

# Objects SQLite creates for itself (autoindexes, sequence bookkeeping).
INTERNAL_OBJECT_NAME_PREFIX = "sqlite_"


class SQLiteSqlglotDDLBuilder(BaseSqlglotDDLBuilder):
    """SQLite-specific DDL query builder.

    Two engine facts shape every override here. SQLite has a single always
    attached namespace, so a declared schema resolves to ``main`` instead of
    qualifying the object with a name no SQLite database has. And SQLite has
    no ``information_schema``: every catalogue query reads ``sqlite_master``
    and the ``pragma_*`` table-valued functions instead.

    ALTER TABLE supports only ADD, RENAME and DROP COLUMN. The statements
    the engine cannot express raise instead of rendering SQL that would fail
    at execution time; the deploy resolves those changes through a rebuild.
    """

    def __init__(self) -> None:
        super().__init__(dialect=SQLITE_DIALECT)

    @staticmethod
    def resolve_schema(schema: str | None) -> str:
        """Resolve any declared schema to the single SQLite namespace."""
        return SQLITE_SCHEMA

    def _table_ref(self, schema: str, table: str) -> str:
        """Render a table reference in the single SQLite namespace."""
        return exp.Table(
            this=exp.to_identifier(table, quoted=True),
            db=exp.to_identifier(self.resolve_schema(schema), quoted=True),
        ).sql(dialect=self._dialect)

    def _identifier(self, name: str) -> str:
        """Render a quoted identifier."""
        return exp.to_identifier(name, quoted=True).sql(dialect=self._dialect)

    def _literal(self, value: str) -> str:
        """Render a safely quoted SQL string literal."""
        return exp.convert(value).sql(dialect=self._dialect)

    def build_create_table(
        self,
        schema: str,
        table: str,
        columns: list[tuple[str, str, bool]],
        primary_key_fields: list[str] | None = None,
        primary_key_name: str | None = None,
        if_not_exists: bool = False,
        column_defaults: dict[str, str] | None = None,
    ) -> str:
        """Build a CREATE TABLE with verbatim type strings.

        The declared type is emitted unchanged: SQLite stores it as written
        and hands it back verbatim through ``pragma_table_info``, so a
        verbatim round trip is what keeps a second deploy a no-op. Named
        primary key constraints are rendered as ``CONSTRAINT … PRIMARY KEY``,
        which SQLite accepts but does not report back, so the reader names
        the key canonically instead.

        Column defaults are part of the statement rather than a follow-up
        ALTER: SQLite cannot set a default on an existing column, so the
        only moment a default can be declared is when the table is written,
        on the first deploy or on a rebuild.
        """
        defaults = column_defaults or {}
        column_parts = [
            f"{self._identifier(column_name)} {column_type}"
            f"{self._default_clause(defaults.get(column_name))}"
            f"{' NOT NULL' if column_not_null else ''}"
            for column_name, column_type, column_not_null in columns
        ]

        if primary_key_fields:
            primary_key_columns = ", ".join(
                self._identifier(field) for field in primary_key_fields
            )
            column_parts.append(f"PRIMARY KEY ({primary_key_columns})")

        exists_clause = "IF NOT EXISTS " if if_not_exists else ""
        columns_sql = ", ".join(column_parts)
        table_ref = self._table_ref(schema=schema, table=table)
        return f"CREATE TABLE {exists_clause}{table_ref} ({columns_sql})"

    def build_drop_table(
        self,
        schema: str,
        table: str,
        if_exists: bool = False,
    ) -> str:
        """Build a DROP TABLE statement."""
        exists_clause = "IF EXISTS " if if_exists else ""
        return f"DROP TABLE {exists_clause}{self._table_ref(schema, table)}"

    def build_drop_view(
        self,
        schema: str,
        table: str,
        if_exists: bool = False,
        cascade: bool = False,
    ) -> str:
        """Build a DROP VIEW statement.

        SQLite has no CASCADE: a dependent view is dropped explicitly by the
        caller, never implicitly by the engine.
        """
        exists_clause = "IF EXISTS " if if_exists else ""
        return f"DROP VIEW {exists_clause}{self._table_ref(schema, table)}"

    def build_truncate_table(
        self,
        schema: str,
        table: str,
    ) -> str:
        """Build the SQLite equivalent of TRUNCATE TABLE.

        SQLite has no TRUNCATE; an unqualified DELETE is optimised into the
        same truncate path by the engine.
        """
        return f"DELETE FROM {self._table_ref(schema, table)}"

    def build_create_schema(
        self,
        schema: str,
        if_not_exists: bool = False,
    ) -> str:
        """Build a no-op statement for schema creation.

        SQLite has no CREATE SCHEMA. Rendering a statement that always
        succeeds keeps the generic bootstrap path working without special
        casing the connector at every call site.
        """
        return "SELECT 1"

    def build_create_index(
        self,
        index_name: str,
        schema: str,
        table: str,
        columns: list[str],
        unique: bool = False,
        if_not_exists: bool = False,
    ) -> str:
        """Build a CREATE INDEX statement.

        The index is schema-qualified but the table is not: SQLite indexes
        live in the same namespace as their table and the syntax rejects a
        qualified table name here.
        """
        unique_keyword = "UNIQUE " if unique else ""
        exists_clause = "IF NOT EXISTS " if if_not_exists else ""
        index_ref = (
            f"{self._identifier(self.resolve_schema(schema))}."
            f"{self._identifier(index_name)}"
        )
        column_list = ", ".join(self._identifier(column) for column in columns)
        return (
            f"CREATE {unique_keyword}INDEX {exists_clause}"
            f"{index_ref} ON {self._identifier(table)} ({column_list})"
        )

    def build_drop_index(
        self,
        schema: str,
        index_name: str,
    ) -> str:
        """Build a DROP INDEX statement."""
        return (
            f"DROP INDEX IF EXISTS "
            f"{self._identifier(self.resolve_schema(schema))}."
            f"{self._identifier(index_name)}"
        )

    @staticmethod
    def _default_clause(default_value: str | None) -> str:
        """Render the DEFAULT part of a column definition."""
        return f" DEFAULT {default_value}" if default_value is not None else ""

    def build_alter_add_column(
        self,
        schema: str,
        table: str,
        column_name: str,
        data_type: str,
        not_null: bool = False,
        default_value: str | None = None,
    ) -> str:
        """Build an ALTER TABLE ADD COLUMN statement.

        SQLite refuses NOT NULL without a default on ADD COLUMN, since the
        existing rows would have nothing to put there. The deploy resolves a
        mandatory new column through a rebuild instead.
        """
        default_clause = self._default_clause(default_value)
        not_null_clause = " NOT NULL" if not_null else ""
        return (
            f"ALTER TABLE {self._table_ref(schema, table)} ADD COLUMN "
            f"{self._identifier(column_name)} {data_type}"
            f"{default_clause}{not_null_clause}"
        )

    def build_alter_drop_column(
        self,
        schema: str,
        table: str,
        column_name: str,
    ) -> str:
        """Build an ALTER TABLE DROP COLUMN statement."""
        return (
            f"ALTER TABLE {self._table_ref(schema, table)} "
            f"DROP COLUMN {self._identifier(column_name)}"
        )

    def build_alter_column_type(
        self,
        schema: str,
        table: str,
        column_name: str,
        new_type: str,
    ) -> str:
        """Reject an in-place type change, which SQLite cannot express."""
        raise NotImplementedError(
            f"SQLite cannot change the type of '{column_name}' on "
            f"'{table}' in place. The table must be rebuilt."
        )

    def build_alter_set_default(
        self,
        schema: str,
        table: str,
        column_name: str,
        default_value: str,
    ) -> str:
        """Reject an in-place default change, which SQLite cannot express."""
        raise NotImplementedError(
            f"SQLite cannot set a default on '{column_name}' of '{table}' "
            f"in place. The table must be rebuilt."
        )

    def build_alter_set_not_null(
        self,
        schema: str,
        table: str,
        column_name: str,
    ) -> str:
        """Reject an in-place nullability change, which SQLite cannot express."""
        raise NotImplementedError(
            f"SQLite cannot make '{column_name}' of '{table}' not nullable "
            f"in place. The table must be rebuilt."
        )

    def build_alter_drop_not_null(
        self,
        schema: str,
        table: str,
        column_name: str,
    ) -> str:
        """Reject an in-place nullability change, which SQLite cannot express."""
        raise NotImplementedError(
            f"SQLite cannot make '{column_name}' of '{table}' nullable "
            f"in place. The table must be rebuilt."
        )

    def build_alter_add_constraint(
        self,
        schema: str,
        table: str,
        constraint_name: str,
        constraint_type: str,
        columns: list[str],
    ) -> str:
        """Reject ALTER TABLE ADD CONSTRAINT, which SQLite does not support."""
        raise NotImplementedError(
            f"SQLite cannot add a {constraint_type} constraint to '{table}' "
            f"in place. The table must be rebuilt."
        )

    def build_alter_drop_constraint(
        self,
        schema: str,
        table: str,
        constraint_name: str,
    ) -> str:
        """Reject ALTER TABLE DROP CONSTRAINT, which SQLite does not support."""
        raise NotImplementedError(
            f"SQLite cannot drop the constraint '{constraint_name}' of "
            f"'{table}' in place. The table must be rebuilt."
        )

    def build_exists_query(
        self,
        schema: str,
        table: str,
    ) -> str:
        """Build a table or view existence check against sqlite_master."""
        return (
            f"SELECT EXISTS (SELECT 1 FROM sqlite_master "
            f"WHERE type IN ('table', 'view') "
            f"AND name = {self._literal(table)}) AS object_exists"
        )

    def build_schema_exists_query(
        self,
        schema: str,
    ) -> str:
        """Build a schema existence check.

        Every declared schema resolves to the always-attached ``main``, so
        the check is a constant: refusing a deploy because a schema is
        missing would be refusing it for a namespace SQLite cannot lack.
        """
        return "SELECT 1 AS schema_exists"

    def build_column_exists_query(
        self,
        schema: str,
        table: str,
        column_name: str,
    ) -> str:
        """Build a column existence check through pragma_table_info."""
        return (
            f"SELECT EXISTS (SELECT 1 FROM pragma_table_info("
            f"{self._literal(table)}) WHERE name = {self._literal(column_name)}"
            f") AS column_exists"
        )

    def build_column_names_query(
        self,
        schema: str,
        table: str,
    ) -> str:
        """Build a query listing a table's column names in physical order."""
        return (
            f"SELECT name AS column_name FROM pragma_table_info("
            f"{self._literal(table)}) ORDER BY cid"
        )

    def _build_object_filter_clause(self, object_name: str | None = None) -> str:
        """Build the WHERE clause filtering sqlite_master to real objects."""
        object_filter = (
            f"AND m.name = {self._literal(object_name)}" if object_name else ""
        )
        return f"""
            WHERE m.type IN ('table', 'view')
            AND m.name NOT LIKE '{INTERNAL_OBJECT_NAME_PREFIX}%'
            {object_filter}
        """

    def build_tables_and_views_query(self, object_name: str | None = None) -> str:
        """Build the query listing tables and views, optionally filtered."""
        return f"""
            SELECT m.name AS table_name,
                   CASE m.type WHEN 'view' THEN 'VIEW' ELSE 'TABLE' END
                        AS table_type
            FROM sqlite_master m
            {self._build_object_filter_clause(object_name=object_name)}
            ORDER BY m.name
        """

    def build_table_columns_query(self, object_name: str | None = None) -> str:
        """Build the query reading the columns of the filtered objects."""
        return f"""
            SELECT m.name AS table_name,
                   c.cid AS ordinal_position,
                   c.name AS column_name,
                   c.type AS data_type,
                   c."notnull" AS not_null,
                   c.dflt_value AS column_default,
                   c.pk AS primary_key_position
            FROM sqlite_master m
            JOIN pragma_table_info(m.name) c
            {self._build_object_filter_clause(object_name=object_name)}
            ORDER BY m.name, c.cid
        """

    def build_index_columns_query(self, object_name: str | None = None) -> str:
        """Build the query reading the indexes of the filtered objects.

        ``origin`` tells a declared index (``c``) from the one SQLite creates
        for an inline UNIQUE (``u``) or for the primary key (``pk``), which is
        what lets the reader map each one onto the right characterisation.
        """
        return f"""
            SELECT m.name AS table_name,
                   il.name AS index_name,
                   il."unique" AS is_unique,
                   il.origin AS index_origin,
                   ii.seqno AS column_position,
                   ii.name AS column_name
            FROM sqlite_master m
            JOIN pragma_index_list(m.name) il
            JOIN pragma_index_info(il.name) ii
            {self._build_object_filter_clause(object_name=object_name)}
            ORDER BY m.name, il.name, ii.seqno
        """

    def build_foreign_keys_query(self, object_name: str | None = None) -> str:
        """Build the query reading the foreign keys of the filtered objects."""
        return f"""
            SELECT m.name AS table_name,
                   fk.id AS constraint_position,
                   fk.seq AS column_position,
                   fk."table" AS referenced_table,
                   fk."from" AS column_name,
                   fk."to" AS referenced_column
            FROM sqlite_master m
            JOIN pragma_foreign_key_list(m.name) fk
            {self._build_object_filter_clause(object_name=object_name)}
            ORDER BY m.name, fk.id, fk.seq
        """

    def build_views_query(self) -> str:
        """Build the query reading view definitions for dependency parsing."""
        return """
            SELECT name AS view_name, sql
            FROM sqlite_master
            WHERE type = 'view' AND sql IS NOT NULL
            ORDER BY name
        """
