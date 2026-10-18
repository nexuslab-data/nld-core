import logging
import socket

ERROR_CATEGORY_CONNECTION: str = "connection failed"
ERROR_CATEGORY_AUTHENTICATION: str = "authentication failed"
ERROR_CATEGORY_MISSING_OBJECT: str = "table or schema missing"
ERROR_CATEGORY_CONFIGURATION: str = "configuration error"
ERROR_CATEGORY_TIMEOUT: str = "timed out"
ERROR_CATEGORY_OTHER: str = "backend error"

_CATEGORY_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        ERROR_CATEGORY_AUTHENTICATION,
        ("authentication", "password", "credential", "permission denied", "auth"),
    ),
    (
        ERROR_CATEGORY_MISSING_OBJECT,
        ("does not exist", "not found", "no such table", "unknown table", "undefined"),
    ),
    (ERROR_CATEGORY_TIMEOUT, ("timed out", "timeout")),
    (
        ERROR_CATEGORY_CONNECTION,
        (
            "connection refused",
            "could not connect",
            "connect",
            "name or service not known",
            "network",
            "unreachable",
            "host",
        ),
    ),
    (
        ERROR_CATEGORY_CONFIGURATION,
        ("unavailable", "missing", "no configuration", "not configured"),
    ),
)

logger = logging.getLogger(__name__)


def categorise_backend_error(error: BaseException) -> str:
    """Return a short, safe category for a backend failure and log the detail.

    Driver messages routinely quote host names, user names and sometimes the
    whole DSN, and the state API may be served beyond the loopback. The
    category is what the browser gets; the exception itself goes to the
    server log where an operator reads it.
    """
    logger.warning(
        "docs live-state backend failure: %s: %s",
        type(error).__name__,
        error,
    )
    if isinstance(error, TimeoutError | socket.timeout):
        return f"{ERROR_CATEGORY_TIMEOUT} ({type(error).__name__})"
    if isinstance(error, ConnectionError | OSError):
        return f"{ERROR_CATEGORY_CONNECTION} ({type(error).__name__})"

    lowered = f"{type(error).__name__} {error}".lower()
    for category, hints in _CATEGORY_HINTS:
        if any(hint in lowered for hint in hints):
            return f"{category} ({type(error).__name__})"
    return f"{ERROR_CATEGORY_OTHER} ({type(error).__name__})"
