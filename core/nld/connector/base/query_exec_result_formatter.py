import sqlglot
from sqlglot import exp

from nld.utils import NldStrEnum

from .query import (
    QueryExecResult,
    SQLOperationType,
)

DEFAULT_SELECT_PREVIEW_ROWS = 10


class QueryExecResultDisplayMode(NldStrEnum):
    """Verbosity selector for `QueryExecResultFormatter`."""

    DETAILED = "DETAILED"
    SUMMARY = "SUMMARY"


_DDL_OPERATIONS: set[SQLOperationType] = {
    SQLOperationType.ALTER_TABLE,
    SQLOperationType.CREATE_TABLE,
    SQLOperationType.CREATE_VIEW,
    SQLOperationType.DROP_TABLE,
    SQLOperationType.DROP_VIEW,
}

_ROW_COUNT_VERBS: dict[SQLOperationType, str] = {
    SQLOperationType.COPY: "copied",
    SQLOperationType.DELETE: "deleted",
    SQLOperationType.INSERT: "inserted",
    SQLOperationType.MERGE: "merged",
    SQLOperationType.SELECT: "returned",
    SQLOperationType.UPDATE: "updated",
}


class QueryExecResultFormatter:
    """Render `QueryExecResult` as plain text for user-facing display.

    The formatter selects a template based on the result's `operation_type`
    and a `QueryExecResultDisplayMode` (summary vs. detailed). Summary mode
    reports only the essential metric (row count or status); detailed mode
    adds the target table, execution duration, and any additional context
    available on the result object.

    Before/after row counts (for INSERT/DELETE/UPSERT/TRUNCATE) are not
    populated from this formatter because they require extra queries against
    the target table. Provide them via `QueryExecResult` before formatting
    if/when that pathway is wired up.
    """

    def __init__(
        self,
        preview_rows: int = DEFAULT_SELECT_PREVIEW_ROWS,
    ) -> None:
        self.preview_rows = preview_rows

    def format(
        self,
        result: QueryExecResult,
        mode: QueryExecResultDisplayMode = QueryExecResultDisplayMode.SUMMARY,
    ) -> str:
        """Return the textual representation of `result` for `mode`."""
        if result.failed():
            return self._format_failure(result=result)

        if mode == QueryExecResultDisplayMode.SUMMARY:
            return self._format_summary(result=result)
        return self._format_detailed(result=result)

    def _format_summary(self, result: QueryExecResult) -> str:
        operation_type = result.operation_type

        if operation_type == SQLOperationType.SELECT:
            return f"SELECT returned {result.get_row_count()} row(s)"
        if operation_type == SQLOperationType.INSERT:
            return f"INSERT affected {result.get_row_count()} row(s)"
        if operation_type == SQLOperationType.UPDATE:
            return f"UPDATE affected {result.get_row_count()} row(s)"
        if operation_type == SQLOperationType.DELETE:
            return f"DELETE affected {result.get_row_count()} row(s)"
        if operation_type == SQLOperationType.MERGE:
            return f"MERGE affected {result.get_row_count()} row(s)"
        if operation_type == SQLOperationType.COPY:
            return f"COPY affected {result.get_row_count()} row(s)"
        if operation_type == SQLOperationType.TRUNCATE:
            return "TRUNCATE executed successfully"
        if operation_type in _DDL_OPERATIONS:
            return f"{operation_type.value} executed successfully"

        if result.get_message():
            return result.get_message()
        query_type = self._safe_query_type(result=result)
        return f"{query_type} completed (rows affected: {result.get_row_count()})"

    def _format_detailed(self, result: QueryExecResult) -> str:
        operation_type = result.operation_type
        lines = [self._format_summary(result=result)]
        target_table = self._extract_target_table(query=result.query)

        if target_table is not None and operation_type != SQLOperationType.SELECT:
            lines.append(f"  target table: {target_table}")

        if operation_type == SQLOperationType.SELECT:
            lines.extend(self._select_detail_lines(result=result))

        lines.append(f"  duration: {self._format_duration(result=result)}")

        if result.get_message() and operation_type in _DDL_OPERATIONS:
            lines.append(f"  message: {result.get_message()}")

        return "\n".join(lines)

    def _select_detail_lines(self, result: QueryExecResult) -> list[str]:
        lines: list[str] = []

        if result.output_structure is not None:
            columns = [
                f"{field.name}:{field.data_type}"
                for field in result.output_structure.fields.values()
            ]
            if columns:
                lines.append("  columns: " + ", ".join(columns))

        data_frame = result.get_output_data_as_df()
        if not data_frame.empty:
            preview = data_frame.head(self.preview_rows)
            preview_text = preview.to_string(index=False)
            indented = "\n".join(f"  {row}" for row in preview_text.splitlines())
            lines.append("  preview:")
            lines.append(indented)

        return lines

    def _format_duration(self, result: QueryExecResult) -> str:
        delta = result.end_tst - result.start_tst
        total_seconds = delta.total_seconds()
        if total_seconds < 1:
            return f"{int(total_seconds * 1000)} ms"
        return f"{total_seconds:.3f} s"

    def format_row_count_line(self, result: QueryExecResult) -> str:
        """Render a single-line row-count summary for a successful query.

        Produces outputs like "439,843 rows merged" for UPSERT/MERGE,
        "N rows inserted" for INSERT, and similar for UPDATE/DELETE/
        SELECT/COPY. DDL and TRUNCATE fall back to a status message
        since row counts are not meaningful.
        """
        if result.failed():
            return self._format_failure(result=result)

        operation_type = result.operation_type
        if operation_type in _ROW_COUNT_VERBS:
            verb = _ROW_COUNT_VERBS[operation_type]
            return f"{result.get_row_count():,} rows {verb}"
        if operation_type == SQLOperationType.TRUNCATE:
            return "table truncated"
        if operation_type in _DDL_OPERATIONS:
            return f"{operation_type.value} executed"
        if result.get_message():
            return result.get_message()
        return f"{self._safe_query_type(result=result)} executed"

    def _format_failure(self, result: QueryExecResult) -> str:
        query_type = self._safe_query_type(result=result)
        return f"{query_type} FAILED: {result.get_error_message()}".rstrip(": ")

    def _safe_query_type(self, result: QueryExecResult) -> str:
        """Return a printable operation label even when the query is empty."""
        if result.operation_type is not None:
            return result.operation_type.value
        stripped = result.query.strip() if result.query else ""
        if not stripped:
            return "QUERY"
        return stripped.split()[0].upper()

    def _extract_target_table(self, query: str) -> str | None:
        """Return the primary target table name for mutating statements.

        Uses sqlglot so dialect-specific syntax is handled consistently
        with `QueryWrapper.detect_operation_type`.
        """
        stripped = query.strip()
        if not stripped:
            return None
        try:
            parsed = sqlglot.parse_one(stripped)
        except sqlglot.errors.ParseError:
            return None

        table = parsed.find(exp.Table)
        if table is None:
            return None
        return table.name
