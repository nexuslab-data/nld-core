from nld.utils.sqlglot.base_dml import BaseSqlglotDMLBuilder


class PostgreSQLSqlglotDMLBuilder(BaseSqlglotDMLBuilder):
    """PostgreSQL-specific DML query builder.

    Uses the default behavior from BaseSqlglotDMLBuilder with the
    postgres dialect. Override methods here when PostgreSQL-specific
    SQL syntax is needed.
    """

    def __init__(self) -> None:
        super().__init__(dialect="postgres")
