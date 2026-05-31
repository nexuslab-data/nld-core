from nld.utils.sqlglot.base_ddl import BaseSqlglotDDLBuilder


class PostgreSQLSqlglotDDLBuilder(BaseSqlglotDDLBuilder):
    """PostgreSQL-specific DDL query builder.

    Uses the default behavior from BaseSqlglotDDLBuilder with the
    postgres dialect. Override methods here when PostgreSQL-specific
    SQL syntax is needed.
    """

    def __init__(self) -> None:
        super().__init__(dialect="postgres")
