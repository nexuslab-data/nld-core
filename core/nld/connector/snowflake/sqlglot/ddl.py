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
    ) -> str:
        """Build a CREATE TABLE with unquoted identifiers."""
        col_defs: list[exp.Expression] = []
        for col_name, col_type, col_not_null in columns:
            constraints = []
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
