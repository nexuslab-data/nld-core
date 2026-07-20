from sqlglot import exp

from nld.utils.sqlglot.base_ddl import BaseSqlglotDDLBuilder


class PostgreSQLSqlglotDDLBuilder(BaseSqlglotDDLBuilder):
    """PostgreSQL-specific DDL and metadata query builder.

    Uses the default behavior from BaseSqlglotDDLBuilder with the
    postgres dialect, and builds the catalog queries the structure
    reader executes — the reader orchestrates and maps, the builder
    owns every piece of SQL.
    """

    def __init__(self) -> None:
        super().__init__(dialect="postgres")

    def _literal(self, value: str) -> str:
        """Render a safely quoted SQL string literal."""
        return exp.convert(value).sql(dialect=self._dialect)

    def _build_object_filter_clause(
        self,
        excluded_schemas: tuple[str, ...],
        schema: str | None = None,
        object_name: str | None = None,
    ) -> str:
        """Build the WHERE clause filtering information_schema.tables.

        Shared by ``build_tables_and_views_query`` and
        ``_build_target_tables_subquery`` — both filter the same
        catalog view by the same excluded-schema/schema/object_name
        shape.
        """
        excluded = ", ".join(self._literal(name) for name in excluded_schemas)
        schema_filter = f"AND table_schema = {self._literal(schema)}" if schema else ""
        object_filter = (
            f"AND table_name = {self._literal(object_name)}" if object_name else ""
        )
        return f"""
            WHERE table_schema NOT IN ({excluded})
            {schema_filter}
            {object_filter}
        """

    def _build_target_tables_subquery(
        self,
        excluded_schemas: tuple[str, ...],
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
        schema: str | None = None,
        object_name: str | None = None,
    ) -> str:
        """Build the query listing tables and views, optionally filtered."""
        filter_clause = self._build_object_filter_clause(
            excluded_schemas=excluded_schemas,
            schema=schema,
            object_name=object_name,
        )
        return f"""
            SELECT table_schema, table_name, table_type
            FROM information_schema.tables
            {filter_clause}
            ORDER BY table_schema, table_name
        """

    def build_table_columns_query(
        self,
        excluded_schemas: tuple[str, ...],
        schema: str | None = None,
        object_name: str | None = None,
    ) -> str:
        """Build the query reading the columns of the filtered tables."""
        target_tables_subquery = self._build_target_tables_subquery(
            excluded_schemas=excluded_schemas,
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
        schema: str | None = None,
        object_name: str | None = None,
    ) -> str:
        """Build the query reading primary key constraints of the filtered tables."""
        target_tables_subquery = self._build_target_tables_subquery(
            excluded_schemas=excluded_schemas,
            schema=schema,
            object_name=object_name,
        )
        return f"""
            WITH target_tables (schema_name, table_name) AS (
                {target_tables_subquery}
            )
            SELECT tc.table_schema, tc.table_name, tc.constraint_name,
                kcu.column_name
            FROM information_schema.table_constraints tc
            INNER JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.constraint_schema = kcu.constraint_schema
            INNER JOIN target_tables t
                ON tc.table_schema = t.schema_name
                AND tc.table_name = t.table_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
            ORDER BY tc.table_schema, tc.table_name, kcu.ordinal_position
        """

    def build_unique_constraints_query(
        self,
        excluded_schemas: tuple[str, ...],
        schema: str | None = None,
        object_name: str | None = None,
    ) -> str:
        """Build the query reading unique constraints of the filtered tables."""
        target_tables_subquery = self._build_target_tables_subquery(
            excluded_schemas=excluded_schemas,
            schema=schema,
            object_name=object_name,
        )
        return f"""
            WITH target_tables (schema_name, table_name) AS (
                {target_tables_subquery}
            )
            SELECT tc.table_schema, tc.table_name, tc.constraint_name,
                kcu.column_name
            FROM information_schema.table_constraints tc
            INNER JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.constraint_schema = kcu.constraint_schema
            INNER JOIN target_tables t
                ON tc.table_schema = t.schema_name
                AND tc.table_name = t.table_name
            WHERE tc.constraint_type = 'UNIQUE'
            ORDER BY tc.table_schema, tc.table_name, tc.constraint_name,
                kcu.ordinal_position
        """

    def build_table_indexes_query(
        self,
        excluded_schemas: tuple[str, ...],
        schema: str | None = None,
        object_name: str | None = None,
    ) -> str:
        """Build the query reading non-constraint indexes of the filtered tables.

        Indexes backing PRIMARY KEY or UNIQUE constraints are excluded;
        expression indexes never match a simple column attribute.
        """
        target_tables_subquery = self._build_target_tables_subquery(
            excluded_schemas=excluded_schemas,
            schema=schema,
            object_name=object_name,
        )
        return f"""
            WITH target_tables (schema_name, table_name) AS (
                {target_tables_subquery}
            )
            SELECT
                n.nspname AS table_schema,
                t.relname AS table_name,
                i.relname AS index_name,
                a.attname AS column_name,
                array_position(ix.indkey, a.attnum) AS col_position
            FROM pg_catalog.pg_index ix
            INNER JOIN pg_catalog.pg_class t
                ON t.oid = ix.indrelid
            INNER JOIN pg_catalog.pg_class i
                ON i.oid = ix.indexrelid
            INNER JOIN pg_catalog.pg_namespace n
                ON n.oid = t.relnamespace
            INNER JOIN pg_catalog.pg_attribute a
                ON a.attrelid = t.oid
                AND a.attnum = ANY(ix.indkey)
                AND a.attnum > 0
            INNER JOIN target_tables tt
                ON n.nspname = tt.schema_name
                AND t.relname = tt.table_name
            LEFT JOIN pg_catalog.pg_constraint c
                ON c.conindid = ix.indexrelid
            WHERE NOT ix.indisunique
                AND NOT ix.indisprimary
                AND c.oid IS NULL
            ORDER BY n.nspname, t.relname, i.relname,
                array_position(ix.indkey, a.attnum)
        """

    def build_dependent_views_query(
        self,
        schema: str,
        object_name: str,
    ) -> str:
        """Build the query listing the views directly depending on an object.

        Uses the pg_depend catalog through the view rewrite rules —
        the reason PostgreSQL blocks ALTER on a referenced column.
        """
        schema_literal = self._literal(schema)
        object_literal = self._literal(object_name)
        return f"""
            SELECT DISTINCT dependent.relname AS view_name
            FROM pg_depend d
            JOIN pg_rewrite r ON r.oid = d.objid
            JOIN pg_class dependent ON dependent.oid = r.ev_class
            JOIN pg_namespace dependent_ns
                ON dependent_ns.oid = dependent.relnamespace
            JOIN pg_class source ON source.oid = d.refobjid
            JOIN pg_namespace source_ns ON source_ns.oid = source.relnamespace
            WHERE source_ns.nspname = {schema_literal}
              AND source.relname = {object_literal}
              AND dependent_ns.nspname = {schema_literal}
              AND dependent.relkind = 'v'
              AND dependent.relname <> source.relname
              AND d.deptype = 'n'
        """

    def build_all_dependent_views_query(
        self,
        schema: str,
    ) -> str:
        """Build the query listing every view-dependency edge in the schema.

        Same catalog walk as ``build_dependent_views_query`` but with
        no ``object_name`` filter — one query returns the dependency
        edge for every table/view pair in the schema, so the caller
        groups the rows into an in-memory graph instead of issuing one
        query per object.
        """
        schema_literal = self._literal(schema)
        return f"""
            SELECT DISTINCT source.relname AS source_name,
                dependent.relname AS view_name
            FROM pg_depend d
            JOIN pg_rewrite r ON r.oid = d.objid
            JOIN pg_class dependent ON dependent.oid = r.ev_class
            JOIN pg_namespace dependent_ns
                ON dependent_ns.oid = dependent.relnamespace
            JOIN pg_class source ON source.oid = d.refobjid
            JOIN pg_namespace source_ns ON source_ns.oid = source.relnamespace
            WHERE source_ns.nspname = {schema_literal}
              AND dependent_ns.nspname = {schema_literal}
              AND dependent.relkind = 'v'
              AND dependent.relname <> source.relname
              AND d.deptype = 'n'
        """
