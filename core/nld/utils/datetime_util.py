import calendar
import datetime
import math

import pandas as pd

# Current time, date and datetime methods

COMPACT_DATETIME_FORMAT = "%Y-%m-%dT%H%M%S.%fZ"
FILESYSTEM_FRIENDLY_DATETIME_FORMAT = "%Y%m%d_%H%M%S"


def get_current_datetime(
    tz: datetime.timezone = datetime.UTC,
) -> datetime.datetime:
    return datetime.datetime.now(tz=tz)


def get_current_date(
    tz: datetime.timezone = datetime.UTC,
) -> datetime.date:
    return get_current_datetime(tz=tz).date()


def get_current_date_as_dt(
    tz: datetime.timezone = datetime.UTC,
) -> datetime.datetime:
    return from_date_to_datetime(get_current_date(tz=tz))


def from_date_to_datetime(
    dt: datetime.date, tz: datetime.timezone = datetime.UTC
) -> datetime.datetime:
    return datetime.datetime.combine(dt, datetime.datetime.min.time()).replace(
        tzinfo=tz
    )


def convert_to_datetime(
    dt: datetime.datetime | datetime.date,
    tz: datetime.timezone = datetime.UTC,
) -> datetime.datetime:
    if type(dt) is datetime.datetime:
        return dt
    return from_date_to_datetime(dt=dt, tz=tz)


def get_current_datetime_as_compact_str() -> str:
    return format_datetime_to_compact_string(get_current_datetime())


def get_current_datetime_as_filesystem_friendly_str() -> str:
    return format_datetime_to_filesystem_friendly_string(get_current_datetime())


# Date/Datetime modification methods


def get_start_of_day(dt: datetime.datetime) -> datetime.datetime:
    return from_date_to_datetime(dt.date())


def get_first_day_of_month(
    dt: datetime.datetime | datetime.date,
) -> datetime.date:
    if isinstance(dt, datetime.datetime):
        return dt.date().replace(day=1)
    return dt.replace(day=1)


def get_first_day_of_year(
    dt: datetime.datetime | datetime.date,
) -> datetime.date:
    if isinstance(dt, datetime.datetime):
        return dt.date().replace(day=1, month=1)
    return dt.replace(day=1, month=1)


def offset_date_in_months(dt: datetime.date, months: int) -> datetime.date:
    new_month = (dt.month + months) % 12
    if new_month == 0:
        new_month = 12
    if (dt.month + months) > 0:
        new_year = dt.year + math.trunc((dt.month + months) / 12)
    else:
        new_year = dt.year - 1 + math.trunc((dt.month + months) / 12)
    return datetime.date(year=new_year, month=new_month, day=1)


def get_elapsed_number_of_days_in_month(month: datetime.date) -> int:
    """
    Return the following depending on the month passed in parameter:
    - For a passed month, this returns the number of days in a month.
    - For the current month, returns days between today and month start.
    - For a future month, this returns 0.
    """
    month = month.replace(day=1)
    today = get_current_date()
    current_month = today.replace(day=1)

    if month == current_month:
        return (today - current_month).days
    elif month < current_month:
        return calendar.monthrange(month.year, month.month)[1]
    else:
        return 0


def diff_in_months(start_dt: datetime.date, end_dt: datetime.date) -> int:
    return (end_dt.year - start_dt.year) * 12 + end_dt.month - start_dt.month


# Type conversion methods


def format_timestamp_to_hour_string(ts: datetime.datetime) -> str:
    return ts.strftime("%H:%M:%S.%f")


def format_datetime_to_date_iso_string(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def format_datetime_to_compact_string(dt: datetime.datetime) -> str:
    return dt.strftime(COMPACT_DATETIME_FORMAT)


def format_datetime_to_filesystem_friendly_string(dt: datetime.datetime) -> str:
    return dt.strftime(FILESYSTEM_FRIENDLY_DATETIME_FORMAT)


def format_timedelta_to_default(td: datetime.timedelta) -> str:
    total_seconds = int(td.total_seconds())
    microseconds = td.microseconds
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:02}.{microseconds:06}"


_DATETIME_PARSE_FORMATS = [
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S.%f%z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d",
]


def parse_datetime_string(value: str) -> datetime.datetime:
    """Parse a datetime string in multiple formats and return a UTC datetime.

    Supports ISO 8601 and common datetime string formats.
    Naive datetimes (without timezone) are interpreted as UTC.

    Args:
        value: A datetime string to parse.

    Returns:
        A UTC timezone-aware datetime.

    Raises:
        ValueError: If the string cannot be parsed in any supported format.
    """
    for fmt in _DATETIME_PARSE_FORMATS:
        try:
            parsed = datetime.datetime.strptime(value, fmt)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=datetime.UTC)
            return parsed.astimezone(tz=datetime.UTC)
        except ValueError:
            continue
    raise ValueError(
        f"Cannot parse datetime string '{value}'. "
        f"Expected ISO 8601 format (e.g. '2025-01-01T00:00:00Z', "
        f"'2025-01-01 00:00:00+00:00', '2025-01-01')."
    )


def ensure_utc_datetime(
    value: datetime.datetime | None,
) -> datetime.datetime | None:
    """Validate that a datetime is UTC timezone-aware.

    Rejects naive datetimes and non-UTC timezones to enforce
    UTC consistency across the incremental state pipeline.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError(
            f"Timestamp must be UTC timezone-aware, received naive datetime: {value}. "
            f"Use datetime.datetime(..., tzinfo=datetime.UTC)."
        )
    if value.utcoffset() != datetime.timedelta(0):
        raise ValueError(
            f"Timestamp must be in UTC timezone, received timezone {value.tzinfo} "
            f"(offset: {value.utcoffset()}). Convert to UTC before storing."
        )
    return value


def normalize_to_utc(
    value: datetime.datetime | None,
) -> datetime.datetime | None:
    """Normalize a datetime to UTC timezone-aware.

    Naive datetimes are interpreted as UTC. Non-UTC aware
    datetimes are converted to UTC. Pandas NaT values are
    treated as None.
    """
    if value is None or pd.isna(value):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.UTC)
    return value.astimezone(tz=datetime.UTC)


def format_to_human_readable_duration(td: datetime.timedelta) -> str:
    total_seconds = td.total_seconds()

    if total_seconds < 60:
        return f"{total_seconds:.3f} seconds"

    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60

    if total_seconds < 3600:
        return f"{minutes} minutes and {seconds:.2f} seconds"

    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours} hours {minutes} minutes and {seconds:.1f} seconds"


def format_to_compact_duration(td: datetime.timedelta) -> str:
    """Format a timedelta to a compact human-readable string."""
    total_seconds = td.total_seconds()

    if total_seconds < 60:
        return f"{total_seconds:.3f}s"

    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60

    if total_seconds < 3600:
        return f"{minutes}m {seconds:.1f}s"

    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours}h {minutes}m {seconds:.0f}s"


def format_timestamp_to_short_hour_string(ts: datetime.datetime) -> str:
    """Format a timestamp to HH:MM:SS without microseconds."""
    return ts.strftime("%H:%M:%S")
