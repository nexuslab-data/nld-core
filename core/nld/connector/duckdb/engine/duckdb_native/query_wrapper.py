from nld.connector.base import (
    QueryOutputType,
    QueryWrapper,
    SQLOperationType,
)

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

# The base framework maps CREATE/DROP for TABLE and VIEW but not
# INDEX.  DuckDB uses CREATE/DROP INDEX extensively (UNIQUE via
# INDEX, structure deployment), so we map them to the closest
# existing operation type to ensure proper transaction handling
# (begin/commit/rollback) in execute_query.
_INDEX_DDL_AS_OPERATION: dict[tuple[str, str], SQLOperationType] = {
    ("CREATE", "INDEX"): SQLOperationType.CREATE_TABLE,
    ("DROP", "INDEX"): SQLOperationType.DROP_TABLE,
}


class DuckDBQueryWrapper(QueryWrapper):
    """DuckDB-specific query wrapper with dialect-aware parsing."""

    def get_dialect(self) -> str:
        return "duckdb"

    @classmethod
    def detect_operation_type(
        cls,
        query: str,
        dialect: str | None = None,
    ) -> SQLOperationType | None:
        """Detect the SQL operation type, including INDEX DDL.

        Extends the base implementation to recognise CREATE INDEX
        and DROP INDEX statements which DuckDB uses for UNIQUE
        constraints.
        """
        import sqlglot
        from sqlglot import exp

        result = super().detect_operation_type(query, dialect=dialect)
        if result is not None:
            return result

        # The base class returns None for CREATE/DROP INDEX because
        # it only maps TABLE and VIEW kinds.  Handle INDEX here.
        stripped = query.strip()
        if not stripped:
            return None

        try:
            parsed = sqlglot.parse_one(stripped, dialect=dialect)
        except sqlglot.errors.ParseError:
            return None

        if isinstance(parsed, exp.Create | exp.Drop):
            kind = (parsed.args.get("kind") or "").upper()
            verb = "CREATE" if isinstance(parsed, exp.Create) else "DROP"
            mapped = _INDEX_DDL_AS_OPERATION.get((verb, kind))
            if mapped is not None:
                return mapped

        return None

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
