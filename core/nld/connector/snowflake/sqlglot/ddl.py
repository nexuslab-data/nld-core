from sqlglot import exp

from nld.utils.sqlglot.base_ddl import BaseSqlglotDDLBuilder


class SnowflakeSqlglotDDLBuilder(BaseSqlglotDDLBuilder):
    """Snowflake-specific DDL query builder.

    Uses unquoted identifiers so Snowflake normalizes them to uppercase,
    ensuring consistent casing between DDL and DML operations.
    """

    def __init__(self) -> None:
        super().__init__(dialect="snowflake")

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
        """Build a CREATE TABLE with unquoted identifiers.

        Defaults are inlined in the column definitions: Snowflake
        cannot add a scalar default to an existing column (``SET
        DEFAULT`` is reserved for sequences), so CREATE is the only
        place a default can be declared.
        """
        defaults = column_defaults or {}
        col_defs: list[exp.Expression] = []
        for col_name, col_type, col_not_null in columns:
            constraints = []
            default_value = defaults.get(col_name)
            if default_value is not None:
                constraints.append(
                    exp.ColumnConstraint(
                        kind=exp.DefaultColumnConstraint(
                            this=exp.maybe_parse(
                                default_value,
                                dialect=self._dialect,
                            ),
                        ),
                    )
                )
            if col_not_null:
                constraints.append(
                    exp.ColumnConstraint(kind=exp.NotNullColumnConstraint())
                )
            col_defs.append(
                exp.ColumnDef(
                    this=exp.to_identifier(col_name, quoted=False),
                    kind=exp.DataType.build(col_type),
                    constraints=constraints if constraints else None,
                )
            )

        if primary_key_fields:
            pk_node = exp.PrimaryKey(
                expressions=[
                    exp.to_identifier(f, quoted=False) for f in primary_key_fields
                ],
            )
            if primary_key_name:
                pk_expression: exp.Expression = exp.Constraint(
                    this=exp.to_identifier(primary_key_name, quoted=False),
                    expressions=[pk_node],
                )
            else:
                pk_expression = pk_node
            col_defs.append(pk_expression)

        create = exp.Create(
            this=exp.Schema(
                this=exp.Table(
                    this=exp.to_identifier(table, quoted=False),
                    db=exp.to_identifier(schema, quoted=False),
                ),
                expressions=col_defs,
            ),
            kind="TABLE",
            exists=if_not_exists,
        )
        return create.sql(dialect=self._dialect)

    def _unquoted_table(self, schema: str, table: str) -> exp.Table:
        """Build an unquoted table reference for Snowflake."""
        return exp.Table(
            this=exp.to_identifier(table, quoted=False),
            db=exp.to_identifier(schema, quoted=False),
        )

    def build_drop_table(
        self,
        schema: str,
        table: str,
        if_exists: bool = False,
    ) -> str:
        """Build a DROP TABLE with unquoted identifiers."""
        drop = exp.Drop(
            this=self._unquoted_table(schema, table),
            kind="TABLE",
            exists=if_exists,
        )
        return drop.sql(dialect=self._dialect)

    def build_truncate_table(
        self,
        schema: str,
        table: str,
    ) -> str:
        """Build a TRUNCATE TABLE with unquoted identifiers."""
        truncate = exp.TruncateTable(
            expressions=[self._unquoted_table(schema, table)],
        )
        return truncate.sql(dialect=self._dialect)

    def build_alter_add_column(
        self,
        schema: str,
        table: str,
        column_name: str,
        data_type: str,
        not_null: bool = False,
        default_value: str | None = None,
    ) -> str:
        """Build ALTER TABLE ADD COLUMN with unquoted identifiers."""
        table_ref = f"{schema}.{table}"
        not_null_clause = " NOT NULL" if not_null else ""
        default_clause = f" DEFAULT {default_value}" if default_value else ""
        return (
            f"ALTER TABLE {table_ref} "
            f"ADD COLUMN {column_name} {data_type}{not_null_clause}{default_clause}"
        )

    def build_alter_drop_column(
        self,
        schema: str,
        table: str,
        column_name: str,
    ) -> str:
        """Build ALTER TABLE DROP COLUMN with unquoted identifiers."""
        table_ref = f"{schema}.{table}"
        return f"ALTER TABLE {table_ref} DROP COLUMN {column_name}"

    def build_alter_column_type(
        self,
        schema: str,
        table: str,
        column_name: str,
        new_type: str,
    ) -> str:
        """Build ALTER TABLE ALTER COLUMN TYPE with unquoted identifiers."""
        table_ref = f"{schema}.{table}"
        return f"ALTER TABLE {table_ref} ALTER COLUMN {column_name} TYPE {new_type}"

    def build_alter_set_not_null(
        self,
        schema: str,
        table: str,
        column_name: str,
    ) -> str:
        """Build ALTER TABLE ALTER COLUMN SET NOT NULL."""
        table_ref = f"{schema}.{table}"
        return f"ALTER TABLE {table_ref} ALTER COLUMN {column_name} SET NOT NULL"

    def build_alter_drop_not_null(
        self,
        schema: str,
        table: str,
        column_name: str,
    ) -> str:
        """Build ALTER TABLE ALTER COLUMN DROP NOT NULL."""
        table_ref = f"{schema}.{table}"
        return f"ALTER TABLE {table_ref} ALTER COLUMN {column_name} DROP NOT NULL"

    def build_alter_add_constraint(
        self,
        schema: str,
        table: str,
        constraint_name: str,
        constraint_type: str,
        columns: list[str],
    ) -> str:
        """Build ALTER TABLE ADD CONSTRAINT with unquoted identifiers."""
        table_ref = f"{schema}.{table}"
        cols = ", ".join(columns)
        return (
            f"ALTER TABLE {table_ref} ADD CONSTRAINT {constraint_name} "
            f"{constraint_type} ({cols})"
        )

    def build_alter_drop_constraint(
        self,
        schema: str,
        table: str,
        constraint_name: str,
    ) -> str:
        """Build ALTER TABLE DROP CONSTRAINT with unquoted identifiers."""
        table_ref = f"{schema}.{table}"
        return f"ALTER TABLE {table_ref} DROP CONSTRAINT {constraint_name}"

    def build_exists_query(
        self,
        schema: str,
        table: str,
    ) -> str:
        """Build a Snowflake-compatible table existence check.

        Snowflake stores unquoted identifiers in uppercase, so we
        upper the comparison values to match.
        """
        schema_lit = exp.convert(schema.upper()).sql(dialect=self._dialect)
        table_lit = exp.convert(table.upper()).sql(dialect=self._dialect)
        return (
            f"SELECT COUNT(*) FROM information_schema.tables "
            f"WHERE table_schema = {schema_lit} "
            f"AND table_name = {table_lit}"
        )

    def build_schema_exists_query(
        self,
        schema: str,
    ) -> str:
        """Build a Snowflake-compatible schema existence check."""
        schema_lit = exp.convert(schema.upper()).sql(dialect=self._dialect)
        return (
            f"SELECT COUNT(*) FROM information_schema.schemata "
            f"WHERE schema_name = {schema_lit}"
        )

    def build_column_names_query(
        self,
        schema: str,
        table: str,
    ) -> str:
        """Build a Snowflake-compatible column-names listing.

        Snowflake stores unquoted identifiers in uppercase, so we
        upper the comparison values to match.
        """
        schema_lit = exp.convert(schema.upper()).sql(dialect=self._dialect)
        table_lit = exp.convert(table.upper()).sql(dialect=self._dialect)
        return (
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_schema = {schema_lit} "
            f"AND table_name = {table_lit} "
            f"ORDER BY ordinal_position"
        )

    # ------------------------------------------------------------------
    # Catalog queries — the builder owns every catalog query the
    # structure reader runs (the PostgreSQL principle).
    # ------------------------------------------------------------------

    @staticmethod
    def quoted_catalog_identifier(name: str) -> str:
        """Quote an identifier for a Snowflake catalog (SHOW) statement.

        Unquoted Snowflake identifiers are stored uppercase, so the
        lowercase nld name is uppercased before quoting; embedded
        double quotes are doubled so a hostile name cannot break the
        statement.
        """
        return '"' + name.upper().replace('"', '""') + '"'

    def _literal(self, value: str) -> str:
        """Render a safely quoted SQL string literal."""
        return exp.convert(value).sql(dialect=self._dialect)

    def _show_scope(self, database: str, schema: str | None) -> str:
        """Render the SHOW command scope for a database or schema."""
        quoted_db = self.quoted_catalog_identifier(database)
        if schema:
            return f"SCHEMA {quoted_db}.{self.quoted_catalog_identifier(schema)}"
        return f"DATABASE {quoted_db}"

    def build_show_objects_query(
        self,
        database: str,
        schema: str | None = None,
        object_pattern: str | None = None,
    ) -> str:
        """Build the SHOW OBJECTS listing, optionally LIKE-filtered.

        SHOW OBJECTS reads the authoritative metadata store, while the
        INFORMATION_SCHEMA.TABLES view can serve stale rows right
        after cross-session DDL.
        """
        scope = self._show_scope(database=database, schema=schema)
        if object_pattern:
            pattern = object_pattern.upper().replace("'", "''")
            return f"SHOW OBJECTS LIKE '{pattern}' IN {scope}"
        return f"SHOW OBJECTS IN {scope}"

    def build_show_views_query(
        self,
        database: str,
        schema: str,
    ) -> str:
        """Build the SHOW VIEWS listing whose text column carries definitions."""
        return f"SHOW VIEWS IN {self._show_scope(database=database, schema=schema)}"

    def build_show_primary_keys_query(
        self,
        database: str,
        schema: str,
        table_name: str | None = None,
    ) -> str:
        """Build the SHOW PRIMARY KEYS command, schema- or table-scoped."""
        if table_name is not None:
            return (
                "SHOW PRIMARY KEYS IN TABLE "
                f"{self.quoted_catalog_identifier(database)}"
                f".{self.quoted_catalog_identifier(schema)}"
                f".{self.quoted_catalog_identifier(table_name)}"
            )
        return (
            f"SHOW PRIMARY KEYS IN {self._show_scope(database=database, schema=schema)}"
        )

    def build_show_unique_keys_query(
        self,
        database: str,
        schema: str,
        table_name: str | None = None,
    ) -> str:
        """Build the SHOW UNIQUE KEYS command, schema- or table-scoped."""
        if table_name is not None:
            return (
                "SHOW UNIQUE KEYS IN TABLE "
                f"{self.quoted_catalog_identifier(database)}"
                f".{self.quoted_catalog_identifier(schema)}"
                f".{self.quoted_catalog_identifier(table_name)}"
            )
        return (
            f"SHOW UNIQUE KEYS IN {self._show_scope(database=database, schema=schema)}"
        )

    def build_table_columns_query(
        self,
        database: str,
        schema: str,
        table_name: str | None = None,
    ) -> str:
        """Build the INFORMATION_SCHEMA.COLUMNS read, optionally per table."""
        table_filter = (
            f"AND TABLE_NAME = {self._literal(table_name)} "
            if table_name is not None
            else ""
        )
        select_columns = (
            "COLUMN_NAME" if table_name is not None else "TABLE_NAME, COLUMN_NAME"
        )
        return (
            f"SELECT {select_columns}, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, "
            "CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_CATALOG = {self._literal(database)} "
            f"AND TABLE_SCHEMA = {self._literal(schema)} "
            f"{table_filter}"
            "ORDER BY "
            + ("" if table_name is not None else "TABLE_NAME, ")
            + "ORDINAL_POSITION"
        )
