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
    ROW_COUNT_MEASURE_ALIAS,
    QualityMeasure,
    QualityMeasureKinds,
)


class RowCountGrowthRule(DataQualityRule):
    """Check that the target row count did not shrink during the run.

    Compares the post-write ``COUNT(*)`` against the baseline count
    captured before the write. When no baseline is available (first run
    against a missing table, capture failure), the check is skipped
    rather than failed so a cold start never degrades the execution.
    """

    name: ClassVar[str] = "row_count_growth"
    requires_baseline: ClassVar[bool] = True

    def build_measures(
        self,
        check: DataQualityCheckConfig,
        context: DataQualityContext,
    ) -> list[QualityMeasure]:
        return [
            QualityMeasure(
                alias=ROW_COUNT_MEASURE_ALIAS,
                kind=QualityMeasureKinds.ROW_COUNT,
            ),
        ]

    def evaluate(
        self,
        check: DataQualityCheckConfig,
        context: DataQualityContext,
        measures: dict[str, Any],
    ) -> DataQualityCheckResult:
        observed = measures.get(ROW_COUNT_MEASURE_ALIAS)
        baseline = context.baseline_row_count

        if baseline is None:
            return DataQualityCheckResult(
                message="Baseline row count is not available; check skipped",
                observed=observed,
                rule=self.name,
                severity=check.severity,
                skipped=True,
                status=DataQualityCheckStatus.VALID,
            )

        is_valid = observed is not None and int(observed) >= baseline
        message = (
            None
            if is_valid
            else (
                f"Target row count {observed} shrank below the "
                f"pre-write count {baseline}"
            )
        )
        # The violation count of a shrink is the number of missing rows.
        missing_rows = (
            baseline - int(observed) if not is_valid and observed is not None else None
        )
        return DataQualityCheckResult(
            expected=f">= {baseline}",
            message=message,
            observed=observed,
            rule=self.name,
            severity=check.severity,
            status=resolve_binary_check_status(is_valid=is_valid),
            violation_count=missing_rows,
        )
