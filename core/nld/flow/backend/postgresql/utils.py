from typing import Final

PSQL_BACKEND_TABLE_PREFIX: Final[str] = "_nld"
PSQL_BACKEND_INCREMENTAL_TABLE_PREFIX: Final[str] = (
    f"{PSQL_BACKEND_TABLE_PREFIX}_incremental"
)
