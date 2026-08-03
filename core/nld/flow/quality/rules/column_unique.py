from typing import Any, ClassVar

from nld.flow.quality.models.config import DataQualityCheckConfig
from nld.flow.quality.models.context import DataQualityContext
from nld.flow.quality.models.result import (
    DataQualityCheckResult,
    DataQualityCheckStatus,
    resolve_binary_check_status,
)
from nld.flow.quality.rules.base import DataQualityRule
from nld.flow.quality.sql_measures import (
    QualityMeasure,
    QualityMeasureKinds,
    build_distinct_count_alias,
    build_non_null_count_alias,
)


class ColumnUniqueRule(DataQualityRule):
    """Check that a column carries no duplicated non-NULL value.

    Compares ``COUNT(column)`` with ``COUNT(DISTINCT column)``; NULLs are
    excluded from both counts, matching SQL unique-constraint semantics
    where NULL keys never collide.
    """

    name: ClassVar[str] = "column_unique"
    requires_column: ClassVar[bool] = True

    def build_measures(
        self,
        check: DataQualityCheckConfig,
        context: DataQualityContext,
    ) -> list[QualityMeasure]:
        column: str = check.column  # type: ignore[assignment]
        return [
            QualityMeasure(
                alias=build_non_null_count_alias(column),
                column=column,
                kind=QualityMeasureKinds.NON_NULL_COUNT,
            ),
            QualityMeasure(
                alias=build_distinct_count_alias(column),
                column=column,
                kind=QualityMeasureKinds.DISTINCT_COUNT,
            ),
        ]

    def evaluate(
        self,
        check: DataQualityCheckConfig,
        context: DataQualityContext,
        measures: dict[str, Any],
    ) -> DataQualityCheckResult:
        column: str = check.column  # type: ignore[assignment]
        non_null = measures.get(build_non_null_count_alias(column))
        distinct = measures.get(build_distinct_count_alias(column))

        if non_null is None or distinct is None:
            return DataQualityCheckResult(
                column=column,
                message="Distinct counts are not available; check skipped",
                rule=self.name,
                severity=check.severity,
                skipped=True,
                status=DataQualityCheckStatus.VALID,
            )

        duplicates = int(non_null) - int(distinct)
        is_valid = duplicates == 0
        # The column lives in the step name and the expectation in the
        # rule name, so neither is repeated in the message or expected.
        message = None if is_valid else f"{duplicates} duplicated value(s)"
        return DataQualityCheckResult(
            column=column,
            message=message,
            observed=duplicates,
            rule=self.name,
            severity=check.severity,
            status=resolve_binary_check_status(is_valid=is_valid),
            violation_count=duplicates,
        )
