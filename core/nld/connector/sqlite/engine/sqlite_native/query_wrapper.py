from nld.connector.base import (
    QueryOutputType,
    QueryWrapper,
    SQLOperationType,
)
from nld.connector.sqlite.constants import SQLITE_DIALECT

_OPERATION_TO_OUTPUT: dict[SQLOperationType, QueryOutputType] = {
    SQLOperationType.ALTER_TABLE: QueryOutputType.MESSAGE,
    SQLOperationType.COPY: QueryOutputType.ROW_COUNT,
    SQLOperationType.CREATE_TABLE: QueryOutputType.MESSAGE,
    SQLOperationType.CREATE_VIEW: QueryOutputType.MESSAGE,
    SQLOperationType.DELETE: QueryOutputType.ROW_COUNT,
    SQLOperationType.DROP_TABLE: QueryOutputType.MESSAGE,
    SQLOperationType.DROP_VIEW: QueryOutputType.MESSAGE,
    SQLOperationType.INSERT: QueryOutputType.ROW_COUNT,
    SQLOperationType.MERGE: QueryOutputType.ROW_COUNT,
    SQLOperationType.SELECT: QueryOutputType.DATASET,
    SQLOperationType.SET: QueryOutputType.MESSAGE,
    SQLOperationType.TRUNCATE: QueryOutputType.MESSAGE,
    SQLOperationType.UPDATE: QueryOutputType.ROW_COUNT,
    SQLOperationType.USE: QueryOutputType.MESSAGE,
}


class SQLiteQueryWrapper(QueryWrapper):
    """SQLite-specific query wrapper with dialect-aware parsing."""

    def get_dialect(self) -> str:
        return SQLITE_DIALECT

    @classmethod
    def detect_operation_type(
        cls,
        query: str,
        dialect: str | None = None,
    ) -> SQLOperationType | None:
        """Detect the SQL operation type, including PRAGMA.

        A PRAGMA is a read returning rows, so it is reported as a SELECT:
        the structure reader queries the catalogue through them.
        """
        result = super().detect_operation_type(query, dialect=dialect)
        if result is not None:
            return result

        stripped = query.strip()
        if not stripped:
            return None
        if stripped.upper().startswith("PRAGMA"):
            return SQLOperationType.SELECT

        return None

    def get_expected_output_type(self) -> QueryOutputType:
        """Derive the expected output type from the operation type.

        Falls back to DATASET when the operation type cannot be determined.
        """
        operation_type = self.operation_type
        if operation_type is None:
            return QueryOutputType.DATASET
        return _OPERATION_TO_OUTPUT.get(
            operation_type,
            QueryOutputType.DATASET,
        )
