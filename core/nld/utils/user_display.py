"""Standard helpers for human-friendly CLI output.

These utilities are shared by the ``nld project info`` /
``nld flow info`` / ``nld structure info`` / ``nld flow state``
families of commands and by any other place in the codebase that
needs to render information to a human operator (as opposed to
machine-readable JSON/YAML payloads). The goal is to keep the
look-and-feel of the CLI consistent and to avoid duplicating the
same ad-hoc formatting code across info/state tasks.

The helpers are intentionally generic. Domain-specific renderers
(e.g. the per-strategy processing-state rendering) should live next
to the task that owns the data model and call into these helpers
for the common building blocks (tables, dates, durations, sections).
"""

import datetime
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from nld.utils.datetime_util import (
    format_to_compact_duration,
    parse_datetime_string,
)

DEFAULT_NA_DISPLAY = "N/A"
DEFAULT_SECTION_WIDTH = 60
DEFAULT_SECTION_HEADER_CHAR = "="
DEFAULT_SECTION_SEPARATOR_CHAR = "-"
DEFAULT_TABLE_INDENT = "  "
DEFAULT_TABLE_SEPARATOR = " | "
DEFAULT_DATETIME_FOR_DISPLAY_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_RANGE_SEPARATOR = " → "


def format_aligned_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    indent: str = DEFAULT_TABLE_INDENT,
    separator: str = DEFAULT_TABLE_SEPARATOR,
) -> list[str]:
    """Format ``headers`` and ``rows`` as a left-aligned ASCII table.

    Returns the rendered lines (header, separator, then rows) without
    a trailing newline. Callers decide how to emit them (``log_info``
    line by line, or ``"\n".join`` for a single string).

    Example::

        format_aligned_table(
            headers=["Name", "Type"],
            rows=[["foo", "INT"], ["bar", "TEXT"]],
        )
        # ['  Name | Type', '  -----------', '  foo  | INT ', '  bar  | TEXT']
    """
    column_widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            if len(cell) > column_widths[index]:
                column_widths[index] = len(cell)

    def _format_row(cells: Sequence[str]) -> str:
        return indent + separator.join(
            cell.ljust(column_widths[index]) for index, cell in enumerate(cells)
        )

    separator_width = sum(column_widths) + len(separator) * (len(headers) - 1)
    lines: list[str] = [_format_row(headers)]
    lines.append(indent + DEFAULT_SECTION_SEPARATOR_CHAR * separator_width)
    for row in rows:
        lines.append(_format_row(row))
    return lines


def format_key_value_lines(
    pairs: list[tuple[str, str]],
    indent: str = DEFAULT_TABLE_INDENT,
    label_separator: str = ": ",
) -> list[str]:
    """Format ``(label, value)`` pairs with labels padded to the same width.

    Returns one indented line per pair, with labels left-aligned to the
    longest label so all values line up vertically. ``label_separator``
    is appended after the padded label (default ``": "``).
    """
    if not pairs:
        return []
    label_width = max(len(label) for label, _ in pairs)
    return [
        f"{indent}{label.ljust(label_width)}{label_separator}{value}"
        for label, value in pairs
    ]


def format_section_header(
    title: str,
    width: int = DEFAULT_SECTION_WIDTH,
    char: str = DEFAULT_SECTION_HEADER_CHAR,
) -> list[str]:
    """Format a banner-style section header (top rule, title, bottom rule)."""
    rule = char * width
    return [rule, title, rule]


def format_section_separator(
    width: int = DEFAULT_SECTION_WIDTH,
    char: str = DEFAULT_SECTION_SEPARATOR_CHAR,
) -> str:
    """Format a horizontal section separator of ``width`` characters."""
    return char * width


def truncate(
    text: str,
    max_length: int,
    ellipsis: str = "…",
) -> str:
    """Shorten ``text`` to ``max_length`` characters with a trailing ellipsis."""
    if len(text) <= max_length:
        return text
    if max_length <= len(ellipsis):
        return ellipsis[:max_length]
    return text[: max_length - len(ellipsis)] + ellipsis


def format_datetime_for_display(
    value: datetime.datetime | None,
    na_display: str = DEFAULT_NA_DISPLAY,
) -> str:
    """Format a datetime for human display in ``YYYY-MM-DD HH:MM:SS`` form."""
    if value is None:
        return na_display
    return value.strftime(DEFAULT_DATETIME_FOR_DISPLAY_FORMAT)


def format_datetime_string_for_display(
    value: Any,
    na_display: str = DEFAULT_NA_DISPLAY,
) -> str:
    """Format a possibly-stringified datetime for human display.

    Accepts native ``datetime`` instances, ISO 8601 strings (Pydantic
    ``model_dump(mode="json")`` output), or ``None``. Falls back to
    light cosmetic cleanup when the value is an unparseable string.
    """
    if value is None:
        return na_display
    if isinstance(value, datetime.datetime):
        return format_datetime_for_display(value=value, na_display=na_display)
    text = str(value)
    try:
        return format_datetime_for_display(value=parse_datetime_string(text))
    except ValueError:
        return text.replace("T", " ")


def format_datetime_range(
    start: datetime.datetime | None,
    end: datetime.datetime | None,
    separator: str = DEFAULT_RANGE_SEPARATOR,
    na_display: str = DEFAULT_NA_DISPLAY,
) -> str | None:
    """Format ``start``/``end`` as a display range, or ``None`` if both absent."""
    if start is None and end is None:
        return None
    return (
        format_datetime_for_display(value=start, na_display=na_display)
        + separator
        + format_datetime_for_display(value=end, na_display=na_display)
    )


def format_datetime_string_range(
    start: Any,
    end: Any,
    separator: str = DEFAULT_RANGE_SEPARATOR,
    na_display: str = DEFAULT_NA_DISPLAY,
) -> str | None:
    """Format ``start``/``end`` strings as a display range.

    Returns ``None`` when both endpoints are absent.
    """
    if start is None and end is None:
        return None
    return (
        format_datetime_string_for_display(value=start, na_display=na_display)
        + separator
        + format_datetime_string_for_display(value=end, na_display=na_display)
    )


def format_duration_between(
    start: datetime.datetime | None,
    end: datetime.datetime | None,
) -> str | None:
    """Format the elapsed duration between two datetimes, or ``None`` if missing."""
    if start is None or end is None:
        return None
    return format_to_compact_duration(td=end - start)


def format_seconds_compact(value: Decimal | float | int) -> str:
    """Format a numeric seconds value to the compact duration form."""
    return format_to_compact_duration(td=datetime.timedelta(seconds=float(value)))
