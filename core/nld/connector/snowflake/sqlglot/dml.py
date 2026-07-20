from typing import Any

from sqlglot import exp

from nld.utils.sqlglot.base_dml import BaseSqlglotDMLBuilder


class SnowflakeSqlglotDMLBuilder(BaseSqlglotDMLBuilder):
    """Snowflake-specific DML query builder.

    Uses unquoted identifiers so Snowflake normalizes them to uppercase.
    """

    def __init__(self) -> None:
        super().__init__(dialect="snowflake")

    def build_delete_from_query(
        self,
        table_path: str,
        sql_query: str,
        key_columns: list[str],
    ) -> str:
        """Build a key-matched DELETE via Snowflake's ``DELETE ... USING``.

        The ``USING`` join form is Snowflake's documented idiom for
        key-based deletes and avoids any doubt about correlated-subquery
        support in DELETE. Identifiers stay unquoted, matching the
        Snowflake DDL convention (upper-folded names).
        """
        join_conditions = " AND ".join(
            f"{table_path}.{column} = _src.{column}" for column in key_columns
        )
        return (
            f"DELETE FROM {table_path} USING ({sql_query}) AS _src "
            f"WHERE {join_conditions}"
        )

    def equality_clause(
        self,
        field: str,
        value: Any,
    ) -> str:
        """Build field = value with unquoted identifier."""
        return exp.EQ(
            this=exp.to_identifier(field, quoted=False),
            expression=exp.convert(value),
        ).sql(dialect=self._dialect)

    def build_count_query(
        self,
        table_path: str,
        where_conditions: dict[str, Any] | None = None,
    ) -> str:
        """Build SELECT COUNT(*) with unquoted identifiers for Snowflake."""
        count_expr = exp.Count(this=exp.Star())
        query = exp.Select(
            expressions=[exp.Alias(this=count_expr, alias="row_count")],
        ).from_(table_path)

        if where_conditions:
            condition: exp.Expression | None = None
            for col, val in where_conditions.items():
                eq = exp.EQ(
                    this=exp.to_identifier(col, quoted=False),
                    expression=exp.convert(val),
                )
                if condition is None:
                    condition = eq
                else:
                    condition = exp.And(
                        this=condition,
                        expression=eq,
                    )
            if condition is not None:
                query = query.where(condition)

        return query.sql(dialect=self._dialect)
