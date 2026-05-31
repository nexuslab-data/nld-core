from typing import Final

DUCKDB_BACKEND_TABLE_PREFIX: Final[str] = "_nld"
DUCKDB_BACKEND_INCREMENTAL_TABLE_PREFIX: Final[str] = (
    f"{DUCKDB_BACKEND_TABLE_PREFIX}_incremental"
)
