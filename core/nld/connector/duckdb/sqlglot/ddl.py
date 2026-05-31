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
