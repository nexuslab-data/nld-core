import datetime
import re
import zoneinfo

from nld.pydantic import NldBaseModel
from nld.utils import NldStrEnum


class PeriodGranularity(NldStrEnum):
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
    YEAR = "YEAR"


class PeriodWeekStart(NldStrEnum):
    MONDAY = "MONDAY"
    SUNDAY = "SUNDAY"


# Canonical period key formats. Every key is lexicographically sortable,
# and the key is the identity persisted in every state model.
_PERIOD_KEY_PATTERNS: dict[str, re.Pattern[str]] = {
    PeriodGranularity.DAY: re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"),
    PeriodGranularity.WEEK: re.compile(r"^(\d{4})-W(\d{2})$"),
    PeriodGranularity.MONTH: re.compile(r"^(\d{4})-(\d{2})$"),
    PeriodGranularity.YEAR: re.compile(r"^(\d{4})$"),
}

_PERIOD_KEY_EXAMPLES: dict[str, str] = {
    PeriodGranularity.DAY: "YYYY-MM-DD (e.g. 2026-07-14)",
    PeriodGranularity.WEEK: "YYYY-Www, ISO week (e.g. 2026-W29)",
    PeriodGranularity.MONTH: "YYYY-MM (e.g. 2026-07)",
    PeriodGranularity.YEAR: "YYYY (e.g. 2026)",
}

# ISO week numbers only exist for weeks starting on Monday, so a week
# starting on Sunday is keyed by its first day instead.
_SUNDAY_WEEK_KEY_PATTERN = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_SUNDAY_WEEK_KEY_EXAMPLE = (
    "YYYY-MM-DD, the Sunday starting the week (e.g. 2026-07-12); any other "
    "day is moved to the Sunday of its week"
)


class PeriodCalendar(NldBaseModel):
    """Calendar arithmetic of a by_target_period flow.

    A period is the half-open date interval ``[start, end)`` of one
    calendar bucket at the configured granularity, identified by its
    canonical key: ``2026-07-14`` (DAY), ``2026-W29`` (ISO WEEK, starting
    on Monday), ``2026-07-12`` (WEEK starting on Sunday, keyed by that
    Sunday), ``2026-07`` (MONTH) or ``2026`` (YEAR). Bounds are calendar
    dates in ``timezone``; they are always derived from the key and never
    persisted.
    """

    granularity: str
    timezone: str = "UTC"
    week_start: str = PeriodWeekStart.MONDAY

    def _is_sunday_week(self) -> bool:
        return (
            self.granularity == PeriodGranularity.WEEK
            and self.week_start == PeriodWeekStart.SUNDAY
        )

    def parse_key(self, key: str) -> datetime.date:
        """Return the first day of the period identified by ``key``.

        Raises:
            ValueError: if the key does not match the granularity format.
        """
        if self._is_sunday_week():
            pattern = _SUNDAY_WEEK_KEY_PATTERN
            example = _SUNDAY_WEEK_KEY_EXAMPLE
        else:
            pattern = _PERIOD_KEY_PATTERNS[self.granularity]
            example = _PERIOD_KEY_EXAMPLES[self.granularity]
        match = pattern.match(key.strip())
        error_message = f"Invalid {self.granularity} period '{key}': expected {example}"
        if match is None:
            raise ValueError(error_message)
        try:
            if self._is_sunday_week():
                return self.get_period_start(
                    datetime.date(
                        year=int(match.group(1)),
                        month=int(match.group(2)),
                        day=int(match.group(3)),
                    )
                )
            if self.granularity == PeriodGranularity.DAY:
                return datetime.date(
                    year=int(match.group(1)),
                    month=int(match.group(2)),
                    day=int(match.group(3)),
                )
            if self.granularity == PeriodGranularity.WEEK:
                return datetime.date.fromisocalendar(
                    year=int(match.group(1)),
                    week=int(match.group(2)),
                    day=1,
                )
            if self.granularity == PeriodGranularity.MONTH:
                return datetime.date(
                    year=int(match.group(1)),
                    month=int(match.group(2)),
                    day=1,
                )
            return datetime.date(
                year=int(match.group(1)),
                month=1,
                day=1,
            )
        except ValueError as exc:
            raise ValueError(error_message) from exc

    def format_key(self, day: datetime.date) -> str:
        """Return the key of the period containing ``day``."""
        if self.granularity == PeriodGranularity.DAY:
            return day.isoformat()
        if self._is_sunday_week():
            return self.get_period_start(day).isoformat()
        if self.granularity == PeriodGranularity.WEEK:
            iso_year, iso_week, _ = day.isocalendar()
            return f"{iso_year:04d}-W{iso_week:02d}"
        if self.granularity == PeriodGranularity.MONTH:
            return f"{day.year:04d}-{day.month:02d}"
        return f"{day.year:04d}"

    def normalize_key(self, key: str) -> str:
        """Validate ``key`` and return its canonical spelling."""
        return self.format_key(self.parse_key(key))

    def get_period_start(self, day: datetime.date) -> datetime.date:
        """Return the first day of the period containing ``day``."""
        if self.granularity == PeriodGranularity.DAY:
            return day
        if self._is_sunday_week():
            return day - datetime.timedelta(days=(day.weekday() + 1) % 7)
        if self.granularity == PeriodGranularity.WEEK:
            return day - datetime.timedelta(days=day.weekday())
        if self.granularity == PeriodGranularity.MONTH:
            return day.replace(day=1)
        return day.replace(
            month=1,
            day=1,
        )

    def get_next_period_start(self, start: datetime.date) -> datetime.date:
        """Return the first day of the period following the one at ``start``."""
        if self.granularity == PeriodGranularity.DAY:
            return start + datetime.timedelta(days=1)
        if self.granularity == PeriodGranularity.WEEK:
            return start + datetime.timedelta(days=7)
        if self.granularity == PeriodGranularity.MONTH:
            if start.month == 12:
                return datetime.date(
                    year=start.year + 1,
                    month=1,
                    day=1,
                )
            return datetime.date(
                year=start.year,
                month=start.month + 1,
                day=1,
            )
        return datetime.date(
            year=start.year + 1,
            month=1,
            day=1,
        )

    def get_previous_period_start(self, start: datetime.date) -> datetime.date:
        """Return the first day of the period preceding the one at ``start``."""
        return self.get_period_start(start - datetime.timedelta(days=1))

    def get_bounds(self, key: str) -> tuple[datetime.date, datetime.date]:
        """Return the half-open ``[start, end)`` bounds of a period."""
        start = self.parse_key(key)
        return start, self.get_next_period_start(start)

    def enumerate_keys(self, from_key: str, to_key: str) -> list[str]:
        """Return every period key from ``from_key`` to ``to_key`` inclusive.

        Raises:
            ValueError: if ``from_key`` is after ``to_key``.
        """
        start = self.parse_key(from_key)
        end = self.parse_key(to_key)
        if start > end:
            raise ValueError(
                f"Period range is reversed: '{from_key}' is after '{to_key}'"
            )
        keys: list[str] = []
        current = start
        while current <= end:
            keys.append(self.format_key(current))
            current = self.get_next_period_start(current)
        return keys

    def get_reference_day(self, moment: datetime.datetime) -> datetime.date:
        """Return the calendar day of ``moment`` in the calendar timezone."""
        return moment.astimezone(zoneinfo.ZoneInfo(self.timezone)).date()

    def get_rolling_keys(
        self,
        moment: datetime.datetime,
        lookback_periods: int,
        include_current_period: bool,
    ) -> list[str]:
        """Return the ``lookback_periods`` periods ending the rolling window.

        The window ends with the period containing ``moment`` when
        ``include_current_period`` is True, and with the last complete
        period otherwise. For example a DAY calendar with one lookback
        period and no current period selects yesterday.
        """
        end_start = self.get_period_start(self.get_reference_day(moment))
        if not include_current_period:
            end_start = self.get_previous_period_start(end_start)
        starts = [end_start]
        while len(starts) < lookback_periods:
            starts.append(self.get_previous_period_start(starts[-1]))
        return [self.format_key(start) for start in reversed(starts)]

    def sort_keys(self, keys: list[str]) -> list[str]:
        """Return ``keys`` sorted chronologically and without duplicates."""
        return sorted(
            set(keys),
            key=self.parse_key,
        )

    def group_contiguous_ranges(
        self,
        keys: list[str],
    ) -> list[tuple[datetime.date, datetime.date]]:
        """Merge periods into the fewest half-open contiguous date ranges.

        For example the MONTH keys 2026-01, 2026-02 and 2026-04 give
        ``[2026-01-01, 2026-03-01)`` and ``[2026-04-01, 2026-05-01)``.
        """
        ranges: list[tuple[datetime.date, datetime.date]] = []
        for key in self.sort_keys(keys):
            start, end = self.get_bounds(key)
            if ranges and ranges[-1][1] == start:
                ranges[-1] = (ranges[-1][0], end)
            else:
                ranges.append((start, end))
        return ranges


def resolve_week_start(granularity: str | None, week_start: str | None) -> str | None:
    """Return the first day of the week of a calendar, None if not weekly.

    A weekly calendar without an explicit week start keeps ISO weeks, which
    start on Monday. For example ``resolve_week_start("WEEK", None)`` gives
    ``MONDAY`` and ``resolve_week_start("MONTH", None)`` gives None.
    """
    if granularity != PeriodGranularity.WEEK:
        return None
    return week_start or PeriodWeekStart.MONDAY


def validate_period_timezone(timezone: str) -> str:
    """Validate an IANA timezone name and return it unchanged.

    Raises:
        ValueError: if the timezone is unknown.
    """
    try:
        zoneinfo.ZoneInfo(timezone)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown period timezone '{timezone}'") from exc
    return timezone
