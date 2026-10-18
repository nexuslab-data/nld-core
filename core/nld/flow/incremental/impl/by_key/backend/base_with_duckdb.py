import abc
import datetime
import json
import os
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any

import pyarrow as pa

from nld.connector.base.connector import DataConnector
from nld.connector.duckdb import DuckDBEngine
from nld.flow.incremental.impl.by_key.backend.base_with_pydantic import (
    ByKeyStateBackendManager as _BaseManager,
)
from nld.flow.incremental.impl.by_key.schema import get_by_key_state_schema
from nld.flow.incremental.impl.by_key.state import (
    TERMINAL_STATUSES,
    ByKeySingleKeyState,
    ByKeyState,
)
from nld.flow.incremental.models import IncrementalStateStatus
from nld.utils.datetime_util import normalize_to_utc

REQUESTED_KEYS_VIEW_NAME = "by_key_requested_keys"
KEY_STATE_ROWS_VIEW_NAME = "by_key_state_rows"
SOURCE_TIMESTAMPS_VIEW_NAME = "by_key_source_timestamps"


def _sql_path_literal(file_path: Path) -> str:
    """Render a file path as a quoted SQL string literal."""
    escaped_path = str(file_path).replace("'", "''")
    return f"'{escaped_path}'"


class ByKeyStateBackendManager[DATA_CONNECTOR: DataConnector[Any]](
    _BaseManager[DATA_CONNECTOR],
):
    """
    Abstract base class for by_key DuckDB state backend managers.

    Inherits from pydantic version since the abstract interface
    is the same for all engines.
    """

    pass


class ByKeyDuckDBKeyStateMixin(abc.ABC):
    """Key state merge for the by_key backends storing the key state as parquet.

    The key state file is only ever read through DuckDB queries: the terminal
    key names, the keys updated in the source, the rows of the keys a run
    processed, and an anti join that writes the merged state. A run therefore
    never holds every stored key in memory, so its footprint follows the keys
    it processes, not the state.

    Every query casts the stored columns to the ``ByKeySingleKeyState``
    parquet schema. Files written by earlier versions typed all-NULL columns
    as INTEGER and may lack the columns added since, which read as NULL.
    """

    @property
    @abc.abstractmethod
    def duckdb_engine(self) -> DuckDBEngine:
        """DuckDB engine running the key state queries."""
        ...

    @property
    @abc.abstractmethod
    def key_state_file_path(self) -> Path:
        """Local path of the key state file this backend writes."""
        ...

    @abc.abstractmethod
    def _current_key_state_file_path(self) -> Path | None:
        """Local path of the stored key state, or None before the first run."""
        ...

    @abc.abstractmethod
    def _publish_key_state_file(self) -> None:
        """Make the key state file just written the stored key state."""
        ...

    def supports_key_state_merge(self) -> bool:
        """The parquet key state is merged on disk."""
        return True

    def read_terminal_key_names(self) -> set[str]:
        """Return the names of the SUCCEEDED and PERMANENTLY_EXCLUDED keys."""
        file_path = self._current_key_state_file_path()
        if file_path is None:
            return set()
        statuses = ", ".join(f"'{status}'" for status in TERMINAL_STATUSES)
        rows = self.duckdb_engine.execute(
            f"SELECT name FROM read_parquet({_sql_path_literal(file_path)}) "
            f"WHERE status IN ({statuses})"
        ).fetchall()
        return {row[0] for row in rows}

    def read_source_updated_key_names(
        self,
        source_last_updated_at: Mapping[str, datetime.datetime],
    ) -> set[str]:
        """Return the SUCCEEDED keys the source updated, read with a join.

        A NULL stored reference never compares as earlier, so a key without a
        stored source timestamp nor a last success is never selected.
        """
        file_path = self._current_key_state_file_path()
        if file_path is None or not source_last_updated_at:
            return set()
        source_timestamps = pa.table(
            {
                "name": pa.array(
                    list(source_last_updated_at.keys()),
                    type=pa.string(),
                ),
                "last_updated_at": pa.array(
                    [
                        normalize_to_utc(last_updated_at)
                        for last_updated_at in source_last_updated_at.values()
                    ],
                    type=pa.timestamp("us", tz="UTC"),
                ),
            }
        )
        self.duckdb_engine.connection.register(
            SOURCE_TIMESTAMPS_VIEW_NAME,
            source_timestamps,
        )
        try:
            rows = self.duckdb_engine.execute(
                f"SELECT key_state.name "
                f"FROM ({self._typed_key_state_query(file_path)}) AS key_state "
                f"JOIN {SOURCE_TIMESTAMPS_VIEW_NAME} AS source "
                f"ON key_state.name = source.name "
                f"WHERE key_state.status = '{IncrementalStateStatus.SUCCEEDED}' "
                f"AND source.last_updated_at > COALESCE("
                f"key_state.source_last_updated_at, "
                f"key_state.last_successfully_processed_at)"
            ).fetchall()
        finally:
            self.duckdb_engine.unregister(SOURCE_TIMESTAMPS_VIEW_NAME)
        return {row[0] for row in rows}

    def read_current_key_states(self, names: Collection[str]) -> ByKeyState:
        """Return the stored state of the given keys, read with a semi join."""
        file_path = self._current_key_state_file_path()
        if file_path is None or not names:
            return ByKeyState(keys={})
        requested_keys = pa.table({"name": pa.array(list(names), type=pa.string())})
        self.duckdb_engine.connection.register(
            REQUESTED_KEYS_VIEW_NAME,
            requested_keys,
        )
        try:
            result = self.duckdb_engine.execute(
                f"SELECT key_state.* FROM ({self._typed_key_state_query(file_path)}) "
                f"AS key_state SEMI JOIN {REQUESTED_KEYS_VIEW_NAME} AS requested "
                f"ON key_state.name = requested.name"
            )
            return self._key_state_from_result(result=result)
        finally:
            self.duckdb_engine.unregister(REQUESTED_KEYS_VIEW_NAME)

    def merge_into_current_state(self, key_states: ByKeyState) -> None:
        """Write the stored keys absent from ``key_states``, then ``key_states``.

        The merged file is written next to the key state file and moved over
        it once complete, so a failed merge leaves the previous file intact.
        """
        target_path = self.key_state_file_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        updates_path = target_path.with_name(f"{target_path.stem}.updates.parquet")
        merged_path = target_path.with_name(f"{target_path.stem}.merged.parquet")
        self._write_key_states_to_parquet(
            state=key_states,
            file_path=updates_path,
        )
        updates_query = self._typed_key_state_query(updates_path)
        current_path = self._current_key_state_file_path()
        if current_path is None:
            merged_query = updates_query
        else:
            merged_query = (
                f"SELECT current_state.* "
                f"FROM ({self._typed_key_state_query(current_path)}) AS current_state "
                f"ANTI JOIN ({updates_query}) AS updates "
                f"ON current_state.name = updates.name "
                f"UNION ALL {updates_query}"
            )
        self.duckdb_engine.execute(
            f"COPY ({merged_query}) TO {_sql_path_literal(merged_path)} "
            f"(FORMAT PARQUET)"
        )
        os.replace(merged_path, target_path)
        updates_path.unlink()
        self._publish_key_state_file()

    def _read_parquet_with_duckdb(self, file_path: Path) -> ByKeyState:
        """Read every key of a key state parquet file."""
        result = self.duckdb_engine.execute(self._typed_key_state_query(file_path))
        return self._key_state_from_result(result=result)

    def _write_parquet_with_duckdb(self, state: ByKeyState) -> None:
        """Write a whole key state as the key state file."""
        self.key_state_file_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_key_states_to_parquet(
            state=state,
            file_path=self.key_state_file_path,
        )

    def _write_key_states_to_parquet(
        self,
        state: ByKeyState,
        file_path: Path,
    ) -> None:
        """Write key states column by column through an Arrow table.

        Building columns instead of one dict per key, and copying the Arrow
        table without materialising it in DuckDB, keeps the write to a single
        compact copy of the keys.
        """
        key_states = list(state.keys.values())
        columns: dict[str, list[Any]] = {
            field_name: [getattr(key_state, field_name) for key_state in key_states]
            for field_name in get_by_key_state_schema().names
            if field_name != "parameters"
        }
        columns["parameters"] = [
            json.dumps(key_state.parameters) if key_state.parameters else None
            for key_state in key_states
        ]
        key_state_rows = pa.Table.from_pydict(
            columns,
            schema=get_by_key_state_schema(),
        )
        self.duckdb_engine.connection.register(
            KEY_STATE_ROWS_VIEW_NAME,
            key_state_rows,
        )
        try:
            self.duckdb_engine.execute(
                f"COPY (SELECT * FROM {KEY_STATE_ROWS_VIEW_NAME}) "
                f"TO {_sql_path_literal(file_path)} (FORMAT PARQUET)"
            )
        finally:
            self.duckdb_engine.unregister(KEY_STATE_ROWS_VIEW_NAME)

    def _typed_key_state_query(self, file_path: Path) -> str:
        """Select a key state file with every column cast to the state schema.

        Example:
            ``SELECT CAST("name" AS VARCHAR) AS "name", ...,
            CAST(NULL AS TIMESTAMP WITH TIME ZONE) AS "source_deleted_at"
            FROM read_parquet('/tmp/key_state.parquet')``
        """
        file_literal = _sql_path_literal(file_path)
        stored_columns = {
            row[0]
            for row in self.duckdb_engine.execute(
                f"DESCRIBE SELECT * FROM read_parquet({file_literal})"
            ).fetchall()
        }
        expressions = [
            (
                f'CAST("{column}" AS {column_type}) AS "{column}"'
                if column in stored_columns
                else f'CAST(NULL AS {column_type}) AS "{column}"'
            )
            for column, column_type in self._key_state_column_types()
        ]
        return f"SELECT {', '.join(expressions)} FROM read_parquet({file_literal})"

    def _key_state_column_types(self) -> list[tuple[str, str]]:
        """Return the DuckDB type of each key state schema column, in order."""
        relation = self.duckdb_engine.connection.from_arrow(
            pa.Table.from_pylist([], schema=get_by_key_state_schema()),
        )
        return [
            (column, str(column_type))
            for column, column_type in zip(
                relation.columns,
                relation.types,
                strict=True,
            )
        ]

    @staticmethod
    def _key_state_from_result(result: Any) -> ByKeyState:
        """Build a key state from a DuckDB result over the key state columns."""
        columns = [description[0] for description in result.description]
        keys: dict[str, ByKeySingleKeyState] = {}
        for row in result.fetchall():
            row_dict = dict(zip(columns, row, strict=True))
            name = row_dict["name"]
            parameters_str = row_dict["parameters"]
            keys[name] = ByKeySingleKeyState(
                name=name,
                status=row_dict["status"] or IncrementalStateStatus.NOT_PROCESSED,
                last_successfully_processed_at=row_dict[
                    "last_successfully_processed_at"
                ],
                last_processed_at=row_dict["last_processed_at"],
                last_process_status=(
                    row_dict["last_process_status"]
                    or IncrementalStateStatus.NOT_PROCESSED
                ),
                last_process_error_message=row_dict["last_process_error_message"],
                first_processed_at=row_dict["first_processed_at"],
                source_deleted_at=row_dict["source_deleted_at"],
                parameters=json.loads(parameters_str) if parameters_str else None,
                source_last_updated_at=row_dict["source_last_updated_at"],
            )
        return ByKeyState(keys=keys)
