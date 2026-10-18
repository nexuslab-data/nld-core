import datetime
import zoneinfo

from sqlglot import exp
from sqlglot.errors import ParseError

from nld.structure import Field
from nld.utils import NldStrEnum

_DATE_TYPES = {
    exp.DataType.Type.DATE,
    exp.DataType.Type.DATE32,
}
_AWARE_TIMESTAMP_TYPES = {
    exp.DataType.Type.TIMESTAMPTZ,
    exp.DataType.Type.TIMESTAMPLTZ,
}
_NAIVE_TIMESTAMP_TYPES = {
    exp.DataType.Type.DATETIME,
    exp.DataType.Type.DATETIME64,
    exp.DataType.Type.TIMESTAMP,
    exp.DataType.Type.TIMESTAMPNTZ,
    exp.DataType.Type.TIMESTAMP_MS,
    exp.DataType.Type.TIMESTAMP_NS,
    exp.DataType.Type.TIMESTAMP_S,
}


class PeriodColumnKind(NldStrEnum):
    """How a period or scan column stores time, which sets its literals.

    A DATE or a naive TIMESTAMP holds wall-clock values of the period
    timezone, so it is compared to local calendar literals. A
    timezone-aware TIMESTAMP holds instants, so it is compared to the UTC
    instant of the local midnight that starts each bound.
    """

    DATE = "DATE"
    NAIVE_TIMESTAMP = "NAIVE_TIMESTAMP"
    AWARE_TIMESTAMP = "AWARE_TIMESTAMP"
    # Engines without temporal types (SQLite) store ISO 8601 text, which
    # compares correctly as text against ISO literals.
    ISO_TEXT = "ISO_TEXT"


# Dialects storing dates and timestamps as ISO 8601 text.
_ISO_TEXT_DIALECTS = {"sqlite"}


def resolve_column_kind(field: Field, dialect: str) -> str:
    """Classify a structure field as a date, naive or aware timestamp.

    The declared data type is parsed with the connector dialect, so
    BigQuery's ``TIMESTAMP`` is an aware type while PostgreSQL's is naive.
    On SQLite every temporal value is ISO text, whatever its declared type.

    Raises:
        ValueError: if the field type is not a date or a timestamp.
    """
    try:
        data_type = exp.DataType.build(
            field.data_type,
            dialect=dialect,
        )
    except (ParseError, ValueError) as exc:
        raise ValueError(
            f"Cannot parse the data type '{field.data_type}' of field "
            f"'{field.name}' for a period column"
        ) from exc
    is_temporal = data_type.this in (
        _DATE_TYPES | _AWARE_TIMESTAMP_TYPES | _NAIVE_TIMESTAMP_TYPES
    )
    if is_temporal and dialect in _ISO_TEXT_DIALECTS:
        return PeriodColumnKind.ISO_TEXT
    if data_type.this in _DATE_TYPES:
        return PeriodColumnKind.DATE
    if data_type.this in _AWARE_TIMESTAMP_TYPES:
        return PeriodColumnKind.AWARE_TIMESTAMP
    if data_type.this in _NAIVE_TIMESTAMP_TYPES:
        return PeriodColumnKind.NAIVE_TIMESTAMP
    raise ValueError(
        f"Field '{field.name}' of type '{field.data_type}' cannot hold a "
        f"period: expected a DATE or a TIMESTAMP"
    )


def build_day_literal(
    day: datetime.date,
    column_kind: str,
    timezone: str,
) -> exp.Expression:
    """Build the literal of the local midnight starting ``day``.

    For example the day 2026-07-14 in Europe/Paris renders as
    ``CAST('2026-07-14' AS DATE)`` for a DATE column and as the instant
    ``CAST('2026-07-13 22:00:00+00:00' AS TIMESTAMPTZ)`` for an aware one.
    """
    if column_kind == PeriodColumnKind.ISO_TEXT:
        # A bare day sorts before every timestamp text of that day, so it
        # is a correct midnight bound for both date and timestamp text.
        return exp.Literal.string(day.isoformat())
    if column_kind == PeriodColumnKind.DATE:
        return exp.cast(
            exp.Literal.string(day.isoformat()),
            to=exp.DataType.Type.DATE,
        )
    local_midnight = datetime.datetime.combine(
        date=day,
        time=datetime.time.min,
    )
    if column_kind == PeriodColumnKind.NAIVE_TIMESTAMP:
        return exp.cast(
            exp.Literal.string(local_midnight.isoformat(sep=" ")),
            to=exp.DataType.Type.TIMESTAMP,
        )
    utc_instant = local_midnight.replace(
        tzinfo=zoneinfo.ZoneInfo(timezone),
    ).astimezone(datetime.UTC)
    return exp.cast(
        exp.Literal.string(utc_instant.isoformat(sep=" ")),
        to=exp.DataType.Type.TIMESTAMPTZ,
    )


def build_instant_literal(
    instant: datetime.datetime,
    column_kind: str,
) -> exp.Expression:
    """Build the literal of a UTC instant for a scan column.

    Naive timestamp columns are read as UTC wall-clock values, the same
    convention as the by_source_tst watermark filter.
    """
    utc_instant = instant.astimezone(datetime.UTC)
    if column_kind == PeriodColumnKind.ISO_TEXT:
        return exp.Literal.string(
            utc_instant.replace(tzinfo=None).isoformat(sep=" "),
        )
    if column_kind == PeriodColumnKind.DATE:
        return exp.cast(
            exp.Literal.string(utc_instant.date().isoformat()),
            to=exp.DataType.Type.DATE,
        )
    if column_kind == PeriodColumnKind.NAIVE_TIMESTAMP:
        return exp.cast(
            exp.Literal.string(utc_instant.replace(tzinfo=None).isoformat(sep=" ")),
            to=exp.DataType.Type.TIMESTAMP,
        )
    return exp.cast(
        exp.Literal.string(utc_instant.isoformat(sep=" ")),
        to=exp.DataType.Type.TIMESTAMPTZ,
    )


def build_period_condition(
    column: exp.Column,
    ranges: list[tuple[datetime.date, datetime.date]],
    column_kind: str,
    timezone: str,
) -> exp.Expression:
    """Build the condition selecting the rows inside the period ranges.

    Each half-open range becomes ``column >= start AND column < end``, so
    the predicate stays index and partition friendly. Ranges are OR-ed and
    an empty list selects no row at all — never every row.
    """
    if not ranges:
        return exp.EQ(
            this=exp.Literal.number(1),
            expression=exp.Literal.number(0),
        )
    conditions: list[exp.Expression] = []
    for start, end in ranges:
        conditions.append(
            exp.and_(
                exp.GTE(
                    this=column.copy(),
                    expression=build_day_literal(
                        day=start,
                        column_kind=column_kind,
                        timezone=timezone,
                    ),
                ),
                exp.LT(
                    this=column.copy(),
                    expression=build_day_literal(
                        day=end,
                        column_kind=column_kind,
                        timezone=timezone,
                    ),
                ),
            )
        )
    if len(conditions) == 1:
        return conditions[0]
    return exp.Paren(this=exp.or_(*conditions))


def build_day_expression(
    column: exp.Column,
    column_kind: str,
    timezone: str,
) -> exp.Expression:
    """Build the expression returning the local calendar day of a value.

    An aware timestamp is first converted to the period timezone, so the
    day never depends on the session timezone of the connection.
    """
    if column_kind == PeriodColumnKind.DATE:
        return column.copy()
    if column_kind == PeriodColumnKind.ISO_TEXT:
        # The day as written, like the text ranges of the filter: a value
        # with an offset stays in the day it names instead of moving to
        # its UTC day.
        return exp.Substring(
            this=column.copy(),
            start=exp.Literal.number(1),
            length=exp.Literal.number(10),
        )
    if column_kind == PeriodColumnKind.NAIVE_TIMESTAMP:
        return exp.cast(
            column.copy(),
            to=exp.DataType.Type.DATE,
        )
    return exp.cast(
        exp.AtTimeZone(
            this=column.copy(),
            zone=exp.Literal.string(timezone),
        ),
        to=exp.DataType.Type.DATE,
    )


def build_period_scan_query(
    table: exp.Table,
    period_field_name: str,
    period_column_kind: str,
    scan_field_name: str | None,
    scan_column_kind: str | None,
    timezone: str,
    scanned_from: datetime.datetime | None,
    dialect: str,
) -> str:
    """Build the query listing the days modified in a source table.

    Returns one row per local calendar day (``period_day``) holding at
    least one row modified at or after ``scanned_from`` (every day when
    None), with the latest modification of that day
    (``last_source_modified_at``). Days are bucketed into periods by the
    caller, which keeps the query identical for every granularity.

    Without scan field, only a full scan is possible: it lists every day
    of the source and the latest modification is NULL.

    Raises:
        ValueError: if ``scanned_from`` is given without scan field.
    """
    if scan_field_name is None and scanned_from is not None:
        raise ValueError("A scan bounded by a watermark needs a scan field.")
    period_column = exp.column(period_field_name)
    last_modified_expression: exp.Expression = (
        exp.Null()
        if scan_field_name is None
        else exp.Max(this=exp.column(scan_field_name))
    )
    day_expression = build_day_expression(
        column=period_column,
        column_kind=period_column_kind,
        timezone=timezone,
    )
    condition: exp.Expression = exp.Not(
        this=exp.Is(
            this=period_column.copy(),
            expression=exp.Null(),
        ),
    )
    if scanned_from is not None and scan_field_name is not None:
        assert scan_column_kind is not None
        scan_column: exp.Expression = exp.column(scan_field_name)
        watermark = build_instant_literal(
            instant=scanned_from,
            column_kind=scan_column_kind,
        )
        if scan_column_kind == PeriodColumnKind.ISO_TEXT:
            # SQLite writes timestamps with a space or a "T" separator and
            # an optional offset: datetime() brings both sides to one
            # UTC spelling before they are compared as text.
            scan_column = exp.Anonymous(this="datetime", expressions=[scan_column])
            watermark = exp.Anonymous(this="datetime", expressions=[watermark])
        condition = exp.and_(
            condition,
            exp.GTE(
                this=scan_column,
                expression=watermark,
            ),
        )
    source_table = table.copy()
    source_table.set("alias", None)
    query = (
        exp.select(
            exp.alias_(
                day_expression,
                alias="period_day",
            ),
            exp.alias_(
                last_modified_expression,
                alias="last_source_modified_at",
            ),
        )
        .from_(source_table)
        .where(condition)
        .group_by(day_expression.copy())
    )
    return str(query.sql(dialect=dialect))
