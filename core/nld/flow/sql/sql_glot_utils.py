import datetime

from sqlglot import exp


def build_technical_timestamps_query(
    table_path: str,
    filter_field_name: str,
    timestamp_fields: list[tuple[str, str, str]],
    started_at: datetime.datetime | None,
    completed_at: datetime.datetime | None,
    dialect: str = "postgres",
) -> str:
    """Build a SELECT MAX(...) query for technical timestamp fields.

    Existing columns are referenced unquoted so they resolve against the
    case the connector folded them to on creation (uppercase on Snowflake,
    lowercase on PostgreSQL); a forced-quoted lowercase identifier would
    not match an uppercase-folded Snowflake column. Output aliases are
    quoted so the result column names are preserved verbatim and can be
    read back by their exact lowercase key regardless of dialect.
    """
    select_expressions = [
        exp.Alias(
            this=exp.Max(
                this=exp.to_identifier(column_name, quoted=False),
            ),
            alias=exp.to_identifier(alias, quoted=True),
        )
        for column_name, _, alias in timestamp_fields
    ]

    query = exp.Select(expressions=select_expressions).from_(table_path)

    column = exp.to_identifier(filter_field_name, quoted=False)

    if started_at is not None:
        query = query.where(
            exp.GTE(
                this=column.copy(),
                expression=exp.convert(started_at.isoformat()),
            ),
        )

    if completed_at is not None:
        query = query.where(
            exp.LT(
                this=column.copy(),
                expression=exp.convert(completed_at.isoformat()),
            ),
        )

    return query.sql(dialect=dialect)
