from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from nld.pydantic import NldBaseModel

from .connector import SQLDataConnector
from .query import QueryWrapper

DEFAULT_TOP_N = 10
DEFAULT_LOW_CARDINALITY_THRESHOLD = 20

# Default data-type tokens used to decide which columns get a min/max measure.
# Engine profilers extend these for their own type vocabulary (e.g. Snowflake's
# ``NUMBER``) by overriding ``numeric_type_tokens`` / ``temporal_type_tokens``.
DEFAULT_NUMERIC_TYPE_TOKENS = (
    "INT",
    "NUMERIC",
    "DECIMAL",
    "REAL",
    "DOUBLE",
    "FLOAT",
    "SERIAL",
    "MONEY",
)
DEFAULT_TEMPORAL_TYPE_TOKENS = ("DATE", "TIME", "TIMESTAMP")


class ColumnProfileSpec(NldBaseModel):
    """A column the profiler should measure.

    Carries only what profiling needs — the physical column name and its
    database data type (used to decide whether a min/max range is meaningful).
    """

    name: str
    data_type: str | None = None


class ProfiledValue(NldBaseModel):
    """One bucket of a value distribution."""

    value: str | int | float | bool | None
    count: int
    pct: float | None = None


class ProfiledDistribution(NldBaseModel):
    """A capped top-N value distribution for a single column."""

    top_n: int = DEFAULT_TOP_N
    truncated: bool = False
    values: list[ProfiledValue] = []


class ProfiledColumn(NldBaseModel):
    """Measured statistics for a single column."""

    non_null: int | None = None
    pct: float | None = None
    distinct: int | None = None
    min: str | int | float | None = None
    max: str | int | float | None = None
    distribution: ProfiledDistribution | None = None


class TableProfile(NldBaseModel):
    """The measured profile of a table (or a sample of it)."""

    row_count: int = 0
    sampled: bool = False
    sample_size: int | None = None
    fraction: float | None = None
    date_from: str | None = None
    date_to: str | None = None
    columns: dict[str, ProfiledColumn] = {}


class ConnectorDataProfiler[CONNECTOR](ABC):
    """Engine-agnostic interface for profiling a physical table.

    A connector exposes a profiler through ``get_data_profiler()`` only when its
    engine can measure data (SQL engines do; a blob-storage connector does not).
    Implementations own both the query creation (delegated to the engine's
    sqlglot builder) and the query execution; callers only pass *what* to
    measure and receive a :class:`TableProfile`.
    """

    def __init__(self, connector: CONNECTOR) -> None:
        self._connector = connector

    @abstractmethod
    def profile(
        self,
        schema_name: str,
        table_name: str,
        columns: list[ColumnProfileSpec],
        date_field: str | None = None,
        sample: int | None = None,
        low_cardinality_threshold: int = DEFAULT_LOW_CARDINALITY_THRESHOLD,
        top_n: int = DEFAULT_TOP_N,
    ) -> TableProfile:
        """Measure ``columns`` of ``schema_name.table_name`` and return a profile."""
        ...


class SQLConnectorDataProfiler[CONNECTOR: SQLDataConnector[Any]](
    ConnectorDataProfiler[CONNECTOR],
):
    """Profiler for SQL connectors.

    Builds every aggregate through the connector's sqlglot DML builder
    (``get_dml_builder()``) and runs it through ``execute_query``. Engine
    specifics (identifier quoting, the random-sampling clause) come from the
    builder's dialect, so this one implementation serves every SQL engine; an
    engine profiler subclass extends ``numeric_type_tokens`` /
    ``temporal_type_tokens`` for its own type vocabulary, and a dialect builder
    can override individual audit queries when needed.
    """

    #: Data-type name fragments that mark a column as numeric (gets min/max).
    numeric_type_tokens: tuple[str, ...] = DEFAULT_NUMERIC_TYPE_TOKENS
    #: Data-type name fragments that mark a column as temporal (gets min/max).
    temporal_type_tokens: tuple[str, ...] = DEFAULT_TEMPORAL_TYPE_TOKENS

    def profile(
        self,
        schema_name: str,
        table_name: str,
        columns: list[ColumnProfileSpec],
        date_field: str | None = None,
        sample: int | None = None,
        low_cardinality_threshold: int = DEFAULT_LOW_CARDINALITY_THRESHOLD,
        top_n: int = DEFAULT_TOP_N,
    ) -> TableProfile:
        builder = self._connector.get_dml_builder()
        self._connector.log_debug(
            f"Running audit query 'audit_row_count' on {schema_name}.{table_name}"
        )
        total = self._connector.get_row_count(f"{schema_name}.{table_name}")

        sampled = sample is not None and 0 < sample < total
        sample_arg = sample if sampled else None
        denominator = (sample if sampled else total) or 0
        fraction = (
            round(sample / total, 4)
            if sampled and total and sample is not None
            else None
        )

        coverage = self._fetch_one(
            builder.build_audit_coverage_query(
                schema_name, table_name, [c.name for c in columns], sample_arg
            ),
            "audit_coverage",
        )

        minmax_columns = [c.name for c in columns if self._has_range(c.data_type)]
        minmax = (
            self._fetch_one(
                builder.build_audit_min_max_query(
                    schema_name, table_name, minmax_columns, sample_arg
                ),
                "audit_min_max",
            )
            if minmax_columns
            else {}
        )

        profiled: dict[str, ProfiledColumn] = {}
        for index, spec in enumerate(columns):
            non_null = int(coverage.get(f"nn_{index}") or 0)
            distinct_raw = coverage.get(f"dc_{index}")
            distinct = None if distinct_raw is None else int(distinct_raw)
            column = ProfiledColumn(
                non_null=non_null,
                pct=self._pct(non_null, denominator),
                distinct=distinct,
            )
            if spec.name in minmax_columns:
                position = minmax_columns.index(spec.name)
                column.min = self._coerce(minmax.get(f"min_{position}"))
                column.max = self._coerce(minmax.get(f"max_{position}"))
            if distinct is not None and 0 < distinct <= low_cardinality_threshold:
                column.distribution = self._profile_distribution(
                    builder,
                    schema_name,
                    table_name,
                    spec.name,
                    top_n,
                    sample_arg,
                    distinct=distinct,
                    denominator=denominator,
                )
            profiled[spec.name] = column

        date_from, date_to = self._profile_date_span(
            builder, schema_name, table_name, date_field, sample_arg
        )

        return TableProfile(
            row_count=total,
            sampled=sampled,
            sample_size=sample if sampled else total,
            fraction=fraction,
            date_from=date_from,
            date_to=date_to,
            columns=profiled,
        )

    # -- query execution -----------------------------------------------------

    def _run(self, query: str, name: str) -> list[dict[str, Any]]:
        self._connector.log_debug(f"Running audit query '{name}'")
        result = self._connector.execute_query(QueryWrapper(query=query, name=name))
        if not result.succeeded():
            raise RuntimeError(
                f"Audit query '{name}' failed: {result.message or 'unknown error'}"
            )
        return result.get_result_records()

    def _fetch_one(self, query: str, name: str) -> dict[str, Any]:
        records = self._run(query, name)
        return records[0] if records else {}

    def _profile_distribution(
        self,
        builder: Any,
        schema_name: str,
        table_name: str,
        column_name: str,
        top_n: int,
        sample_arg: int | None,
        distinct: int,
        denominator: int,
    ) -> ProfiledDistribution:
        records = self._run(
            builder.build_audit_distribution_query(
                schema_name, table_name, column_name, top_n, sample_arg
            ),
            f"audit_dist_{column_name}",
        )
        values = [
            ProfiledValue(
                value=self._coerce(record.get("value")),
                count=int(record.get("count", 0)),
                pct=self._pct(int(record.get("count", 0)), denominator),
            )
            for record in records
        ]
        return ProfiledDistribution(
            top_n=top_n,
            truncated=distinct > top_n,
            values=values,
        )

    def _profile_date_span(
        self,
        builder: Any,
        schema_name: str,
        table_name: str,
        date_field: str | None,
        sample_arg: int | None,
    ) -> tuple[str | None, str | None]:
        if not date_field:
            return None, None
        record = self._fetch_one(
            builder.build_audit_date_span_query(
                schema_name, table_name, date_field, sample_arg
            ),
            "audit_date_span",
        )
        date_from = self._as_date_str(self._coerce(record.get("date_from")))
        date_to = self._as_date_str(self._coerce(record.get("date_to")))
        return date_from, date_to

    # -- classification & coercion ------------------------------------------

    def _has_range(self, data_type: str | None) -> bool:
        upper = (data_type or "").upper()
        return any(
            token in upper
            for token in self.numeric_type_tokens + self.temporal_type_tokens
        )

    @staticmethod
    def _pct(part: int, total: int) -> float | None:
        if not total:
            return None
        return round(100.0 * part / total, 1)

    @staticmethod
    def _coerce(value: Any) -> Any:
        if value is None or isinstance(value, bool | int | float | str):
            return value
        if isinstance(value, Decimal):
            return float(value)
        return str(value)

    @staticmethod
    def _as_date_str(value: Any) -> str | None:
        if value is None:
            return None
        return str(value)[:10]
