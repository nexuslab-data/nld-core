import logging
from typing import cast

from .base import (
    BaseEvent,
    EventLevel,
    StandardDebugEvent,
    StandardErrorEvent,
    StandardInfoEvent,
    StandardWarningEvent,
)


class NldLogger(logging.Logger):
    """Custom logger class for the package.

    This logger should be set as the logger class for the package logging
    by using the following line of code in the main method:
        - logging.setLoggerClass(NldLogger)
    """

    def __init__(self, name: str, level: int = 0) -> None:
        super().__init__(name, level)

    def log_event(self, event: BaseEvent) -> None:
        self.log(event.level(), event.message())


def _get_default_logger() -> logging.Logger:
    """Return the shared 'nld' logger.

    `logging.setLoggerClass(NldLogger)` only affects loggers created after the
    call, so a `getLogger("nld")` issued before `LoggerManager` runs yields a
    plain `logging.Logger` that is then cached for the rest of the process.
    Callers must tolerate either class - see `_emit_event`.
    """
    return logging.getLogger("nld")


def _emit_event(logger: logging.Logger, event: BaseEvent) -> None:
    """Dispatch an event regardless of whether the logger is an `NldLogger`.

    Falls back to `Logger.log(level, message)` when the cached logger predates
    `LoggerManager` (otherwise calling `log_event` would AttributeError).
    """
    if isinstance(logger, NldLogger):
        logger.log_event(event)
    else:
        logger.log(event.level(), event.message())


def log_event_default(event: BaseEvent) -> None:
    _emit_event(_get_default_logger(), event)


def log_info_default(message: str) -> None:
    _emit_event(_get_default_logger(), StandardInfoEvent(msg=message))


def log_debug_default(message: str) -> None:
    _emit_event(_get_default_logger(), StandardDebugEvent(msg=message))


def log_error_default(message: str) -> None:
    _emit_event(_get_default_logger(), StandardErrorEvent(msg=message))


def log_warn_default(message: str) -> None:
    _emit_event(_get_default_logger(), StandardWarningEvent(msg=message))


def log_event(
    event: BaseEvent,
    logger: NldLogger | None = None,
) -> None:
    if logger is not None and isinstance(type(logger), NldLogger):
        logger.log_event(event)
    else:
        log_event_default(event)


class NldLoggable:
    """Interface for all loggable classes.

    Initializes the local logger and provides standard logging methods.
    """

    def __init__(self) -> None:
        self._init_logger()

    def _init_logger(self) -> None:
        self.logger: NldLogger = cast(
            NldLogger, logging.getLogger(self.__class__.__name__)
        )

    def log_event(self, event: BaseEvent) -> None:
        log_event(event, self.logger)

    def log_debug(self, message: str) -> None:
        self.logger.log(EventLevel.DEBUG, message)

    def log_info(self, message: str) -> None:
        self.logger.log(EventLevel.INFO, message)

    def log_warn(self, message: str) -> None:
        self.logger.log(EventLevel.WARN, message)

    def log_error(self, message: str) -> None:
        self.logger.log(EventLevel.ERROR, message)


class StandardNldFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if record.levelno == logging.INFO:
            fmt = "%(message)s"
        else:
            fmt = "%(levelname)s: %(message)s"
        formatter = logging.Formatter(fmt)
        return formatter.format(record)


_DEFAULT_FORMATTER = logging.Formatter("[%(asctime)s] [%(levelname)s] - %(message)s")


class LoggerManager:
    """Logger manager for initializing default logging.

    Initializes the default logging with custom DF classes and levels.
    """

    def __init__(
        self,
        level: int = logging.DEBUG,
        formatter: logging.Formatter | None = None,
    ) -> None:
        if formatter is None:
            formatter = _DEFAULT_FORMATTER
        logging.setLoggerClass(NldLogger)
        logging.addLevelName(EventLevel.TEST, "TEST")

        root = logging.getLogger()
        root.setLevel(level)

        root.handlers.clear()

        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root.addHandler(handler)


def init_logger_for_tests() -> None:
    LoggerManager(EventLevel.TEST)
