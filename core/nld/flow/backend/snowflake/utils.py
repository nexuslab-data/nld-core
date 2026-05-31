from typing import Final

SNOWFLAKE_BACKEND_TABLE_PREFIX: Final[str] = "_nld"
SNOWFLAKE_BACKEND_INCREMENTAL_TABLE_PREFIX: Final[str] = (
    f"{SNOWFLAKE_BACKEND_TABLE_PREFIX}_incremental"
)
