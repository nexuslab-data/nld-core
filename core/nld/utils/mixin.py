import copy
import logging
from collections.abc import Sequence
from typing import Self, cast

from nld.exceptions import BaseModelDeepCopyException
from nld.logging import BaseEvent, EventLevel, NldLogger
from nld.utils.user_display import (
    DEFAULT_SECTION_HEADER_CHAR,
    DEFAULT_SECTION_SEPARATOR_CHAR,
    DEFAULT_SECTION_WIDTH,
    format_aligned_table,
    format_key_value_lines,
    format_section_separator,
)


class NldMixIn:
    """MixIn for all the NLD classes.

    Initializes the local logger.
    """

    def __init__(self) -> None:
        self._init_logger()

    def _init_logger(self) -> None:
        self.logger = cast(NldLogger, logging.getLogger(self.__class__.__name__))

    def log_event(self, event: BaseEvent) -> None:
        self.logger.log_event(event)

    def log_debug(self, message: str) -> None:
        self.logger.log(EventLevel.DEBUG, message)

    def log_info(self, message: str) -> None:
        self.logger.log(EventLevel.INFO, message)

    def log_warn(self, message: str) -> None:
        self.logger.log(EventLevel.WARN, message)

    def log_error(self, message: str) -> None:
        self.logger.log(EventLevel.ERROR, message)

    def log_empty_line(self) -> None:
        # Emits a blank line to space out human-readable CLI sections.
        self.log_info("")

    def log_separator_line(
        self,
        width: int = DEFAULT_SECTION_WIDTH,
        char: str = DEFAULT_SECTION_SEPARATOR_CHAR,
    ) -> None:
        # Emits a horizontal rule delimiting human-readable CLI sections.
        self.log_info(format_section_separator(width=width, char=char))

    def log_section_header(
        self,
        *title_lines: str,
        width: int = DEFAULT_SECTION_WIDTH,
        char: str = DEFAULT_SECTION_HEADER_CHAR,
    ) -> None:
        """Emit a banner header: a rule, the title lines, then a rule.

        Accepts a variable number of ``title_lines`` so callers can append
        optional lines (namespace, description, ...) only when present.
        """
        self.log_separator_line(width=width, char=char)
        for line in title_lines:
            self.log_info(line)
        self.log_separator_line(width=width, char=char)

    def log_aligned_table(
        self,
        headers: Sequence[str],
        rows: Sequence[Sequence[str]],
        length_limitation: dict[str, int] | None = None,
    ) -> None:
        """Render an auto-width aligned table, one log line per output row.

        ``length_limitation`` maps a header name to a maximum cell length for
        that column; longer cells are truncated and suffixed with ``...``.
        """
        if length_limitation:
            limits = {
                index: length_limitation[header]
                for index, header in enumerate(headers)
                if header in length_limitation
            }
            if limits:
                truncated: list[list[str]] = []
                for row in rows:
                    cells = list(row)
                    for index, limit in limits.items():
                        if index < len(cells):
                            value = str(cells[index])
                            if len(value) > limit:
                                cells[index] = value[:limit] + "..."
                    truncated.append(cells)
                rows = truncated
        for line in format_aligned_table(headers=headers, rows=rows):
            self.log_info(line)

    def log_key_value_lines(
        self,
        pairs: list[tuple[str, str]],
    ) -> None:
        # Logs label/value pairs with labels padded to a common width.
        for line in format_key_value_lines(pairs=pairs):
            self.log_info(line)

    @classmethod
    def deep_copy(cls, self: Self) -> Self:
        """Creates a deep copy of this object.

        Returns:
            A new object cloned from this object instance.
        """
        if not isinstance(self, cls):
            raise BaseModelDeepCopyException(self, cls)
        return copy.deepcopy(self)
