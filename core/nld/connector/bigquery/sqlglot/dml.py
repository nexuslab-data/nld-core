from nld.utils.sqlglot.base_dml import BaseSqlglotDMLBuilder
from nld.utils.sqlglot.utils import quote_identifier, quote_table


class BigQuerySqlglotDMLBuilder(BaseSqlglotDMLBuilder):
    """BigQuery-specific DML query builder.

    Uses the default behavior from BaseSqlglotDMLBuilder with the
    bigquery dialect. Override methods here when BigQuery-specific
    SQL syntax is needed.
    """

    def __init__(self) -> None:
        super().__init__(dialect="bigquery")

    def build_mark_absent_rows_deleted_query(
        self,
        table_path: str,
        sql_query: str,
        key_columns: list[str],
        deletion_flag_column: str,
    ) -> str:
        """Build the logical-delete UPDATE with backtick-quoted identifiers.

        Overrides the base form to quote the table and columns, matching
        the connector's systematic BigQuery quoting. ``table_path`` is a
        qualified ``dataset.table`` reference (the flow always passes a
        qualified target), split here and requoted via ``quote_table``.
        """
        schema_name, _, table_name = table_path.rpartition(".")
        table_ref = quote_table(
            schema=schema_name,
            table=table_name,
            dialect=self._dialect,
        )
        flag_col = quote_identifier(
            deletion_flag_column,
            dialect=self._dialect,
        )
        join_conditions = " AND ".join(
            f"_subq.{quote_identifier(column, dialect=self._dialect)} = "
            f"{table_ref}.{quote_identifier(column, dialect=self._dialect)}"
            for column in key_columns
        )
        return (
            f"UPDATE {table_ref} "
            f"SET {flag_col} = TRUE "
            f"WHERE COALESCE({flag_col}, FALSE) = FALSE "
            f"AND NOT EXISTS ("
            f"SELECT 1 FROM ({sql_query}) AS _subq "
            f"WHERE {join_conditions}"
            f")"
        )
