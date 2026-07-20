import csv
import datetime
import os
from enum import StrEnum
from typing import Any, cast

import jinja2
import pandas as pd
import sqlglot
from pydantic import Field, PrivateAttr
from sqlglot import exp

from nld.logging import log_event
from nld.logging.events import CSVFileWriteSuccessful
from nld.pydantic import NldBaseModel
from nld.structure import Structure
from nld.utils import NldStrEnum

from .exceptions import (
    QueryExecutionException,
    SingleValueResultException,
)


class SQLOperationType(NldStrEnum):
    """SQL operation keywords used to classify queries before execution."""

    ALTER_TABLE = "ALTER_TABLE"
    COPY = "COPY"
    CREATE_TABLE = "CREATE_TABLE"
    CREATE_VIEW = "CREATE_VIEW"
    DELETE = "DELETE"
    DROP_TABLE = "DROP_TABLE"
    DROP_VIEW = "DROP_VIEW"
    INSERT = "INSERT"
    MERGE = "MERGE"
    SELECT = "SELECT"
    SET = "SET"
    TRUNCATE = "TRUNCATE"
    UPDATE = "UPDATE"
    USE = "USE"


class QueryOutputType(NldStrEnum):
    """Expected output type for a SQL query based on its operation."""

    DATASET = "DATASET"
    MESSAGE = "MESSAGE"
    ROW_COUNT = "ROW_COUNT"


_EXPRESSION_TO_OPERATION: dict[type[exp.Expression], SQLOperationType] = {
    exp.Select: SQLOperationType.SELECT,
    exp.Insert: SQLOperationType.INSERT,
    exp.Update: SQLOperationType.UPDATE,
    exp.Delete: SQLOperationType.DELETE,
    exp.Merge: SQLOperationType.MERGE,
    exp.TruncateTable: SQLOperationType.TRUNCATE,
    exp.Copy: SQLOperationType.COPY,
    exp.Set: SQLOperationType.SET,
    exp.Use: SQLOperationType.USE,
}

_CREATE_KIND_TO_OPERATION: dict[str, SQLOperationType] = {
    "TABLE": SQLOperationType.CREATE_TABLE,
    "VIEW": SQLOperationType.CREATE_VIEW,
}

_DROP_KIND_TO_OPERATION: dict[str, SQLOperationType] = {
    "TABLE": SQLOperationType.DROP_TABLE,
    "VIEW": SQLOperationType.DROP_VIEW,
}


class QueryWrapper(NldBaseModel):
    query: str
    interpreted_query: str | None = None
    name: str = ""
    params: dict[str, str | dict[str, Any]] = Field(default_factory=dict)
    runtime_exception_message: str | None = None

    def update_interpreted_query(self) -> None:
        self.interpreted_query = jinja2.Template(self.query).render(**self.params)

    def get_interpreted_query(self) -> str:
        if self.interpreted_query is None:
            self.update_interpreted_query()
        return cast(str, self.interpreted_query)

    @property
    def operation_type(self) -> SQLOperationType | None:
        """Auto-detect the SQL operation type from the query text."""
        return self.detect_operation_type(
            self.query,
            dialect=self.get_dialect(),
        )

    @classmethod
    def detect_operation_type(
        cls,
        query: str,
        dialect: str | None = None,
    ) -> SQLOperationType | None:
        """Extract the SQL operation type from the query text using SQLGlot."""
        stripped = query.strip()
        if not stripped:
            return None

        try:
            parsed = sqlglot.parse_one(
                stripped,
                dialect=dialect,
            )
        except sqlglot.errors.ParseError:
            return None

        expression_type = type(parsed)

        if expression_type in _EXPRESSION_TO_OPERATION:
            return _EXPRESSION_TO_OPERATION[expression_type]

        if expression_type is exp.Create:
            kind = parsed.args.get("kind", "").upper()
            return _CREATE_KIND_TO_OPERATION.get(kind)

        if expression_type is exp.Drop:
            kind = parsed.args.get("kind", "").upper()
            return _DROP_KIND_TO_OPERATION.get(kind)

        if expression_type is exp.Alter:
            kind = parsed.args.get("kind", "").upper()
            if kind == "TABLE":
                return SQLOperationType.ALTER_TABLE
            return None

        return None

    def get_dialect(self) -> str | None:
        """Return the SQL dialect for parsing.

        Subclasses override this to return their specific
        dialect (e.g. 'postgres', 'snowflake').
        """
        return None

    def get_expected_output_type(self) -> QueryOutputType:
        """Derive the expected output type from the operation type.

        Subclasses must implement this to define connector-specific
        operation-to-output mappings.

        Falls back to DATASET when the operation type cannot be
        determined (e.g. CTEs starting with WITH).
        """
        raise NotImplementedError

    def raise_runtime_exception(self) -> None:
        if self.runtime_exception_message is not None:
            raise QueryExecutionException(
                error_message=self.runtime_exception_message.format(**self.params)
            )


class QueryExecResultStatus(StrEnum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


class QueryExecResult(NldBaseModel):
    """
    Query Execution Result Wrapper

    All the queries returned by the method execute_query should return this object
    """

    query_name: str
    exec_status: str
    query: str
    query_id: str | None
    output_structure: Structure | None
    start_tst: datetime.datetime
    end_tst: datetime.datetime
    message: str | None = None
    operation_type: SQLOperationType | None = None
    row_count: int | None = None
    _result_data: list[Any] | None = PrivateAttr(default=None)

    def __init__(self, result_data: list[Any] | None = None, **data: Any) -> None:
        super().__init__(**data)
        self._result_data = result_data

    # Methods for checking execution status

    def succeeded(self) -> bool:
        return self.exec_status == QueryExecResultStatus.SUCCESS

    def failed(self) -> bool:
        return self.exec_status == QueryExecResultStatus.ERROR

    def get_error_message(self) -> str:
        if self.failed():
            if self._result_data is not None:
                error_message = self._result_data[0]
                if error_message is not None:
                    if type(error_message) is str:
                        return (
                            error_message.replace("\n", " ").replace("\r", " ").strip()
                        )
        return ""

    def raise_on_error(self, context: str | None = None) -> None:
        """Fail loudly when the result carries an ERROR status.

        Some connector engines report a rejected statement as an
        ERROR-status result instead of raising; callers for which a
        failure must not degrade into an empty result (metadata
        reads, deploy DDL) use this to surface it.
        """
        if not self.failed():
            return
        details = self.get_error_message()
        message = context or f"Query '{self.query_name}' failed"
        raise QueryExecutionException(
            message + (f" — {details}" if details else ""),
        )

    def get_row_count(self) -> int:
        """Return the number of affected rows, defaulting to 0."""
        return self.row_count or 0

    def get_message(self) -> str:
        """Return the result message, defaulting to empty string."""
        return self.message or ""

    @property
    def query_type(self) -> str:
        if self.operation_type is not None:
            return self.operation_type.value
        return self.query.strip().split()[0].upper()

    # Methods for dictionary conversion

    def to_dict(
        self,
        exclude_none: bool = True,
        exclude_unset: bool = True,
        exclude_defaults: bool = True,
        preserve_references: bool = True,  # noqa: ARG002
    ) -> dict[str, Any]:
        return {
            "query_name": self.query_name,
            "exec_status": self.exec_status,
            "query": self.query,
            "query_id": self.query_id,
            "message": self.message,
            "operation_type": (
                self.operation_type.value if self.operation_type is not None else None
            ),
            "result_data": self._result_data,
            "result_data_header": (
                ", ".join(
                    [field.name for field in self.output_structure.fields.values()]
                )
                if self.output_structure is not None
                else ""
            ),
            "row_count": self.row_count,
            "start_tst": self.start_tst.strftime("%Y%m%d%H%M%S%f"),
            "end_tst": self.end_tst.strftime("%Y%m%d%H%M%S%f"),
        }

    # Methods for Pandas DataFrame conversion

    def get_result_df(self) -> pd.DataFrame:
        if self.output_structure is not None:
            return pd.DataFrame(
                self._result_data,
                columns=[field.name for field in self.output_structure.fields.values()],
            )
        else:
            return pd.DataFrame()

    def get_result_records(self) -> list[dict[str, Any]]:
        """Return the output data as a list of column-name → value dicts.

        Bypasses the pandas DataFrame layer used by :meth:`get_result_df`
        so that values keep their native Python types from the underlying
        cursor — in particular, NULLs stay as ``None`` (pandas would promote
        them to ``NaN`` in numeric columns) and JSONB columns stay as
        ``dict`` / ``list`` (pandas stores them in object dtype but a
        ``DataFrame -> dict`` round-trip preserves them only when the
        connector adapter has already parsed them).

        Handles both tuple rows (the default psycopg2 cursor) and
        dict-like rows (e.g. ``RealDictCursor``).
        """
        if self.output_structure is None or self._result_data is None:
            return []
        field_names = [field.name for field in self.output_structure.fields.values()]
        records: list[dict[str, Any]] = []
        for row in self._result_data:
            if isinstance(row, dict):
                records.append({name: row[name] for name in field_names})
            else:
                records.append(dict(zip(field_names, row, strict=True)))
        return records

    # @deprecated
    def get_result_dict(self) -> Any:
        if self.succeeded():
            result_df = self.get_result_df()
            if result_df.shape[0] == 0:
                self.log_error(f"Query {self.query_name} retrieved O rows.")
            else:
                if result_df.shape[0] > 1:
                    self.log_error(
                        f"Query {self.query_name} contains more than 1 rows. "
                        f"The method to get dictionary result is meant "
                        f"for single rows result set"
                    )
                else:
                    return result_df.iloc[0].to_dict()
        else:
            self.log_error(f"Query {self.query_name} encountered an error.")

        return {}

    def get_result_single_value(self) -> Any:
        if self.failed():
            # The query failed at the connector level; surface the
            # original error instead of masking it as "0 rows".
            error_msg = f"Query {self.query_name} failed: {self.get_error_message()}"
            self.log_error(error_msg)
            raise SingleValueResultException(error_message=error_msg)
        result_df = self.get_result_df()
        if result_df.shape[0] == 0:
            error_msg = f"Query {self.query_name} retrieved 0 rows."
            self.log_error(error_msg)
            raise SingleValueResultException(error_message=error_msg)
        else:
            if result_df.shape[1] == 1:
                return result_df.iloc[0, 0]
            else:
                self.log_warn(
                    f"Query {self.query_name} contains more than 1 column. The "
                    f"first column"
                    f"data is used for returning the single value."
                )
                return result_df.iloc[0, 0]


class QueryExecResults(list[QueryExecResult]):
    def __init__(self) -> None:
        super().__init__()

    def get_status(self) -> str:
        if self.has_succeeded():
            return QueryExecResultStatus.SUCCESS
        return QueryExecResultStatus.ERROR

    def has_succeeded(self) -> bool:
        for query_exec_result in self:
            if query_exec_result.failed():
                return False
        return True

    def has_failed(self) -> bool:
        for query_exec_result in self:
            if query_exec_result.failed():
                return True
        return False

    def get_number_of_results(self) -> int:
        return len(self)

    def to_str(self) -> str:
        return ", ".join(
            [str(query_exec_result.to_dict()) for query_exec_result in self]
        )

    def report_exec_status(self) -> str:
        return "\n".join(
            [
                (
                    query_exec_result.query_name
                    if query_exec_result.query_name is not None
                    else ""
                )
                + " : "
                + query_exec_result.exec_status
                + (
                    "(" + query_exec_result.get_error_message() + ")"
                    if query_exec_result.failed()
                    else ""
                )
                for query_exec_result in self
            ]
        )

    def get_csv_header(self) -> list[str]:
        return [
            "Query Name",
            "Query",
            "Operation Type",
            "Execution Status",
            "Execution Message",
            "Row Count",
            "Message",
            "Start Tst",
            "End Tst",
        ]

    def get_csv_rows(self) -> list[list[Any]]:
        return [
            [
                query_exec_result.query_name,
                query_exec_result.query[
                    0 : (
                        100
                        if len(query_exec_result.query) >= 100
                        else len(query_exec_result.query)
                    )
                ]
                .replace("\n", " ")
                .replace("\r", " ")
                .replace(";", " "),
                (
                    query_exec_result.operation_type.value
                    if query_exec_result.operation_type is not None
                    else ""
                ),
                query_exec_result.exec_status,
                query_exec_result.get_error_message(),
                query_exec_result.get_row_count(),
                query_exec_result.get_message(),
                query_exec_result.start_tst.strftime("%Y-%m-%d %H:%M:%S.%f"),
                query_exec_result.end_tst.strftime("%Y-%m-%d %H:%M:%S.%f"),
            ]
            for query_exec_result in self
        ]

    def to_csv(
        self,
        file_path: str,
        delimiter: str = ";",
        newline: str = "\n",
        quotechar: str = '"',
    ) -> None:
        with open(file_path, "w", newline=newline) as csvfile:
            writer = csv.writer(csvfile, delimiter=delimiter, quotechar=quotechar)
            writer.writerow(self.get_csv_header())
            for query_exec_result_csv_row in self.get_csv_rows():
                writer.writerow(query_exec_result_csv_row)
        log_event(
            CSVFileWriteSuccessful(
                file_path=file_path, object_type_name=QueryExecResults.__name__
            ),
        )


class QueryExecResultUtil:
    @classmethod
    def write_script_exec_results_to_csv(
        cls,
        script_results: list[tuple[str, QueryExecResults]],
        file_path: str,
        delimiter: str = ";",
        newline: str = "\n",
        quotechar: str = '"',
    ) -> None:
        with open(file_path, "w", newline=newline) as csvfile:
            writer = csv.writer(csvfile, delimiter=delimiter, quotechar=quotechar)
            writer.writerow(
                [
                    "Script Name",
                    "Script Status",
                    "Query Name",
                    "Query",
                    "Operation Type",
                    "Query Status",
                    "Execution Message",
                    "Row Count",
                    "Message",
                    "Start Tst",
                    "End Tst",
                ]
            )
            for script_result in script_results:
                script_name = os.path.basename(script_result[0])
                query_exec_result = script_result[1]
                for query_exec_result_csv_row in query_exec_result.get_csv_rows():
                    csv_row = [script_name, query_exec_result.get_status()]
                    csv_row.extend(query_exec_result_csv_row)
                    writer.writerow(csv_row)
        log_event(
            CSVFileWriteSuccessful(
                file_path=file_path, object_type_name="ScriptExecResults"
            ),
        )
