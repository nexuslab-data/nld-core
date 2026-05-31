from nld.utils.sqlglot.base_dml import BaseSqlglotDMLBuilder


class BigQuerySqlglotDMLBuilder(BaseSqlglotDMLBuilder):
    """BigQuery-specific DML query builder.

    Uses the default behavior from BaseSqlglotDMLBuilder with the
    bigquery dialect. Override methods here when BigQuery-specific
    SQL syntax is needed.
    """

    def __init__(self) -> None:
        super().__init__(dialect="bigquery")
