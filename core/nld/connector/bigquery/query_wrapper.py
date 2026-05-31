from nld.connector.base import (
    QueryOutputType,
    QueryWrapper,
    SQLOperationType,
)

_OPERATION_TO_OUTPUT: dict[SQLOperationType, QueryOutputType] = {
    SQLOperationType.ALTER_TABLE: QueryOutputType.MESSAGE,
    SQLOperationType.CREATE_TABLE: QueryOutputType.MESSAGE,
    SQLOperationType.CREATE_VIEW: QueryOutputType.MESSAGE,
    SQLOperationType.DELETE: QueryOutputType.ROW_COUNT,
    SQLOperationType.DROP_TABLE: QueryOutputType.MESSAGE,
    SQLOperationType.DROP_VIEW: QueryOutputType.MESSAGE,
    SQLOperationType.INSERT: QueryOutputType.ROW_COUNT,
    SQLOperationType.MERGE: QueryOutputType.ROW_COUNT,
    SQLOperationType.SELECT: QueryOutputType.DATASET,
    SQLOperationType.TRUNCATE: QueryOutputType.MESSAGE,
    SQLOperationType.UPDATE: QueryOutputType.ROW_COUNT,
}


class BigQueryQueryWrapper(QueryWrapper):
    """BigQuery-specific query wrapper with dialect-aware parsing."""

    def get_dialect(self) -> str:
        return "bigquery"

    def get_expected_output_type(self) -> QueryOutputType:
        """Derive the expected output type from the operation type.

        Falls back to DATASET when the operation type cannot be
        determined (e.g. unrecognised statements).
        """
        op_type = self.operation_type
        if op_type is None:
            return QueryOutputType.DATASET
        return _OPERATION_TO_OUTPUT.get(
            op_type,
            QueryOutputType.DATASET,
        )
