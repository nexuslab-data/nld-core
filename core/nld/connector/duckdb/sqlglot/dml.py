import re

from nld.utils.sqlglot.base_dml import BaseSqlglotDMLBuilder

# Match the bare CURRENT_TIMESTAMP keyword (word-boundary, case-insensitive)
# so compound expressions like "CURRENT_TIMESTAMP + INTERVAL '1 day'" are
# translated correctly while column names containing the substring (e.g.
# "current_timestamp_col") are left alone.
_CURRENT_TIMESTAMP_PATTERN = re.compile(
    r"\bCURRENT_TIMESTAMP\b",
    re.IGNORECASE,
)


class DuckDBSqlglotDMLBuilder(BaseSqlglotDMLBuilder):
    """DuckDB-specific DML query builder.

    Overrides ``build_on_conflict_clause`` to translate the
    ``CURRENT_TIMESTAMP`` keyword to ``NOW()`` in UPDATE expressions.

    DuckDB resolves bare identifiers as column references first
    inside ``ON CONFLICT DO UPDATE SET`` — so ``CURRENT_TIMESTAMP``
    would be misinterpreted as a column name.  ``NOW()`` is an
    unambiguous function call.

    The translation handles compound expressions
    (e.g. ``CURRENT_TIMESTAMP + INTERVAL '1 day'`` becomes
    ``NOW() + INTERVAL '1 day'``).  Word boundaries prevent
    accidental substitution inside identifiers.
    """

    def __init__(self) -> None:
        super().__init__(dialect="duckdb")

    def build_on_conflict_clause(
        self,
        insert_column_list: list[str],
        conflict_merge_fields: list[str],
        table_name: str,
        exclude_from_update: list[str] | None = None,
        expression_overrides: dict[str, str] | None = None,
        exclude_from_match: list[str] | None = None,
    ) -> str:
        """Translate CURRENT_TIMESTAMP → NOW() in overrides for DuckDB."""
        if expression_overrides:
            expression_overrides = {
                col: _CURRENT_TIMESTAMP_PATTERN.sub("NOW()", expr)
                for col, expr in expression_overrides.items()
            }
        return super().build_on_conflict_clause(
            insert_column_list=insert_column_list,
            conflict_merge_fields=conflict_merge_fields,
            table_name=table_name,
            exclude_from_update=exclude_from_update,
            expression_overrides=expression_overrides,
            exclude_from_match=exclude_from_match,
        )
