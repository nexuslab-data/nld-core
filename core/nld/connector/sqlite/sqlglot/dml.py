from nld.connector.sqlite.constants import SQLITE_DIALECT
from nld.utils.sqlglot.base_dml import BaseSqlglotDMLBuilder


class SQLiteSqlglotDMLBuilder(BaseSqlglotDMLBuilder):
    """SQLite-specific DML query builder.

    SQLite implements the PostgreSQL ``INSERT … ON CONFLICT DO UPDATE`` form
    natively, including ``excluded`` and ``IS NOT`` change detection, so the
    base builder's output needs no translation.
    """

    def __init__(self) -> None:
        super().__init__(dialect=SQLITE_DIALECT)
