from typing import Final

BIGQUERY_BACKEND_TABLE_PREFIX: Final[str] = "_nld"
BIGQUERY_BACKEND_INCREMENTAL_TABLE_PREFIX: Final[str] = (
    f"{BIGQUERY_BACKEND_TABLE_PREFIX}_incremental"
)
