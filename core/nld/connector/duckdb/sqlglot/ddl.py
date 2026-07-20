from sqlglot import exp

from nld.utils.sqlglot.base_ddl import BaseSqlglotDDLBuilder
from nld.utils.sqlglot.utils import quoted_table


class DuckDBSqlglotDDLBuilder(BaseSqlglotDDLBuilder):
    """DuckDB-specific DDL query builder.

    Overrides ``build_create_table`` because sqlglot's DuckDB
    generator maps VARCHAR → TEXT via its TYPE_MAPPING, but
    DuckDB's information_schema always reports VARCHAR.  Using
    the AST-based ``exp.DataType.build()`` would emit TEXT in
    the DDL while the structure reader reads back VARCHAR,
    causing a false diff on every deploy cycle.

    The override uses string formatting (same pattern as
    ``build_alter_add_column`` in the base class) so the type
    string passes through verbatim.
    """

    def __init__(self) -> None:
        super().__init__(dialect="duckdb")

    @staticmethod
    def is_unbounded_string_type(data_type: str) -> bool:
        """Check if a type is a DuckDB string type with no length.

        DuckDB ignores length limits on string types and
        information_schema never reports them back.  Emitting
        them in DDL would cause a false diff every deploy cycle.
        """
        return data_type.upper() in ("VARCHAR", "TEXT", "CHARACTER VARYING")

    @classmethod
    def normalize_string_type(cls, data_type: str) -> str:
        """Normalize TEXT and CHARACTER VARYING to VARCHAR.

        The structure reader always returns VARCHAR for all string
        types.  The DDL must emit VARCHAR too, otherwise a YAML
        structure with ``data_type: TEXT`` would cause a perpetual
        diff on every deploy cycle (desired=TEXT vs current=VARCHAR).
        """
        if cls.is_unbounded_string_type(data_type=data_type):
            return "VARCHAR"
        return data_type

    def build_type_expression(
        self,
        data_type: str,
        length: int = 0,
        precision: int = 0,
    ) -> str:
        """Build a type expression with DuckDB string normalization."""
        upper_type = data_type.upper()
        if self.is_unbounded_string_type(data_type=upper_type):
            return self.normalize_string_type(data_type=upper_type)
        return super().build_type_expression(
            data_type=upper_type,
            length=length,
            precision=precision,
        )

    def build_create_table(
        self,
        schema: str,
        table: str,
        columns: list[tuple[str, str, bool]],
        primary_key_fields: list[str] | None = None,
        primary_key_name: str | None = None,
        if_not_exists: bool = False,
    ) -> str:
        """Build a CREATE TABLE with verbatim type strings.

        Uses string formatting instead of sqlglot AST for column
        definitions to bypass the VARCHAR → TEXT normalization.
        """
        table_ref = quoted_table(
            schema=schema,
            table=table,
        ).sql(dialect=self._dialect)

        col_parts: list[str] = []
        for col_name, col_type, col_not_null in columns:
            col_id = exp.to_identifier(
                col_name,
                quoted=True,
            ).sql(dialect=self._dialect)
            not_null_clause = " NOT NULL" if col_not_null else ""
            col_parts.append(f"{col_id} {col_type}{not_null_clause}")

        if primary_key_fields:
            pk_cols = ", ".join(
                exp.to_identifier(f, quoted=True).sql(dialect=self._dialect)
                for f in primary_key_fields
            )
            col_parts.append(f"PRIMARY KEY ({pk_cols})")

        exists_clause = "IF NOT EXISTS " if if_not_exists else ""
        cols_sql = ", ".join(col_parts)
        return f"CREATE TABLE {exists_clause}{table_ref} ({cols_sql})"

    def build_schema_exists_query(self, schema: str) -> str:
        """Build a schema existence check compatible with DuckDB.

        DuckDB does not support ``SELECT FROM`` without a column list
        (PostgreSQL extension).  Use ``SELECT 1 FROM`` instead.
        """
        schema_lit = exp.convert(schema).sql(dialect=self._dialect)
        return (
            f"SELECT EXISTS (SELECT 1 FROM information_schema.schemata "
            f"WHERE schema_name = {schema_lit})"
        )

    # ------------------------------------------------------------------
    # Catalog queries — the builder owns every catalog query the
    # structure reader runs (the PostgreSQL principle).
    # ------------------------------------------------------------------

    def _literal(self, value: str) -> str:
        """Render a safely quoted SQL string literal."""
        return exp.convert(value).sql(dialect=self._dialect)

    def _build_object_filter_clause(
        self,
        excluded_schemas: tuple[str, ...],
        catalog: str | None = None,
        schema: str | None = None,
        object_name: str | None = None,
    ) -> str:
        """Build the WHERE clause filtering information_schema.tables."""
        excluded = ", ".join(self._literal(name) for name in excluded_schemas)
        catalog_filter = (
            f"AND table_catalog = {self._literal(catalog)}" if catalog else ""
        )
        schema_filter = f"AND table_schema = {self._literal(schema)}" if schema else ""
        object_filter = (
            f"AND table_name = {self._literal(object_name)}" if object_name else ""
        )
        return f"""
            WHERE table_schema NOT IN ({excluded})
            {catalog_filter}
            {schema_filter}
            {object_filter}
        """

    def _build_target_tables_subquery(
        self,
        excluded_schemas: tuple[str, ...],
        catalog: str | None = None,
        schema: str | None = None,
        object_name: str | None = None,
    ) -> str:
        """Build the target_tables CTE body as an inline filtered subquery.

        Replaces a materialized ``VALUES`` list of (schema, table)
        keys — computed by the caller through a prior round trip —
        with the same catalog filter ``build_tables_and_views_query``
        applies, evaluated directly by the database.
        """
        filter_clause = self._build_object_filter_clause(
            excluded_schemas=excluded_schemas,
            catalog=catalog,
            schema=schema,
            object_name=object_name,
        )
        return f"""
            SELECT table_schema, table_name
            FROM information_schema.tables
            {filter_clause}
        """

    def build_tables_and_views_query(
        self,
        excluded_schemas: tuple[str, ...],
        catalog: str | None = None,
        schema: str | None = None,
        object_name: str | None = None,
    ) -> str:
        """Build the query listing tables and views, optionally filtered."""
        filter_clause = self._build_object_filter_clause(
            excluded_schemas=excluded_schemas,
            catalog=catalog,
            schema=schema,
            object_name=object_name,
        )
        return f"""
            SELECT table_catalog, table_schema, table_name, table_type
            FROM information_schema.tables
            {filter_clause}
            ORDER BY table_schema, table_name
        """

    def build_table_columns_query(
        self,
        excluded_schemas: tuple[str, ...],
        catalog: str | None = None,
        schema: str | None = None,
        object_name: str | None = None,
    ) -> str:
        """Build the query reading the columns of the filtered tables."""
        target_tables_subquery = self._build_target_tables_subquery(
            excluded_schemas=excluded_schemas,
            catalog=catalog,
            schema=schema,
            object_name=object_name,
        )
        return f"""
            WITH target_tables (schema_name, table_name) AS (
                {target_tables_subquery}
            )
            SELECT
                c.table_schema,
                c.table_name,
                c.column_name,
                c.data_type,
                c.character_maximum_length,
                c.numeric_precision,
                c.numeric_scale,
                c.is_nullable,
                c.column_default
            FROM information_schema.columns c
            INNER JOIN target_tables t
                ON c.table_schema = t.schema_name
                AND c.table_name = t.table_name
            ORDER BY c.table_schema, c.table_name, c.ordinal_position
        """

    def build_primary_key_columns_query(
        self,
        excluded_schemas: tuple[str, ...],
        catalog: str | None = None,
        schema: str | None = None,
        object_name: str | None = None,
    ) -> str:
        """Build the query reading primary key constraints of the filtered tables."""
        target_tables_subquery = self._build_target_tables_subquery(
            excluded_schemas=excluded_schemas,
            catalog=catalog,
            schema=schema,
            object_name=object_name,
        )
        catalog_filter = (
            f"AND tc.table_catalog = {self._literal(catalog)}" if catalog else ""
        )
        return f"""
            WITH target_tables (schema_name, table_name) AS (
                {target_tables_subquery}
            )
            SELECT tc.table_schema, tc.table_name,
                   tc.constraint_name, kcu.column_name
            FROM information_schema.table_constraints tc
            INNER JOIN information_schema.key_column_usage kcu
                ON tc.constraint_catalog = kcu.constraint_catalog
                AND tc.constraint_name = kcu.constraint_name
                AND tc.constraint_schema = kcu.constraint_schema
            INNER JOIN target_tables t
                ON tc.table_schema = t.schema_name
                AND tc.table_name = t.table_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
                {catalog_filter}
            ORDER BY tc.table_schema, tc.table_name,
                     kcu.ordinal_position
        """

    def build_unique_indexes_query(
        self,
        excluded_schemas: tuple[str, ...],
        catalog: str | None = None,
        schema: str | None = None,
        object_name: str | None = None,
    ) -> str:
        """Build the query reading unique indexes of the filtered tables.

        DuckDB implements UNIQUE constraints as unique indexes; they
        never appear in information_schema.table_constraints.
        """
        target_tables_subquery = self._build_target_tables_subquery(
            excluded_schemas=excluded_schemas,
            catalog=catalog,
            schema=schema,
            object_name=object_name,
        )
        catalog_filter = (
            f"AND i.database_name = {self._literal(catalog)}" if catalog else ""
        )
        return f"""
            WITH target_tables (schema_name, table_name) AS (
                {target_tables_subquery}
            )
            SELECT
                i.schema_name AS table_schema,
                i.table_name,
                i.index_name,
                i.sql AS index_sql
            FROM duckdb_indexes() i
            INNER JOIN target_tables t
                ON i.schema_name = t.schema_name
                AND i.table_name = t.table_name
            WHERE i.is_unique AND NOT i.is_primary
                {catalog_filter}
            ORDER BY i.schema_name, i.table_name, i.index_name
        """

    def build_table_indexes_query(
        self,
        excluded_schemas: tuple[str, ...],
        catalog: str | None = None,
        schema: str | None = None,
        object_name: str | None = None,
    ) -> str:
        """Build the query reading non-unique indexes of the filtered tables."""
        target_tables_subquery = self._build_target_tables_subquery(
            excluded_schemas=excluded_schemas,
            catalog=catalog,
            schema=schema,
            object_name=object_name,
        )
        catalog_filter = (
            f"AND i.database_name = {self._literal(catalog)}" if catalog else ""
        )
        return f"""
            WITH target_tables (schema_name, table_name) AS (
                {target_tables_subquery}
            )
            SELECT
                i.schema_name AS table_schema,
                i.table_name,
                i.index_name,
                i.is_unique,
                i.sql AS index_sql
            FROM duckdb_indexes() i
            INNER JOIN target_tables t
                ON i.schema_name = t.schema_name
                AND i.table_name = t.table_name
            WHERE NOT i.is_unique
                {catalog_filter}
            ORDER BY i.schema_name, i.table_name, i.index_name
        """

    def build_views_query(
        self,
        schema: str,
    ) -> str:
        """Build the query reading view definitions for dependency parsing."""
        return f"""
            SELECT view_name, sql FROM duckdb_views()
            WHERE schema_name = {self._literal(schema)} AND NOT internal
        """
