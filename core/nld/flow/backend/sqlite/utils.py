from typing import Final

SQLITE_BACKEND_TABLE_PREFIX: Final[str] = "_nld"
SQLITE_BACKEND_INCREMENTAL_TABLE_PREFIX: Final[str] = (
    f"{SQLITE_BACKEND_TABLE_PREFIX}_incremental"
)
