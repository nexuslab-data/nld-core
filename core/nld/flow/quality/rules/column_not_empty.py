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
    build_empty_string_count_alias,
    build_non_null_count_alias,
)


class ColumnNotEmptyRule(DataQualityRule):
    """Check that a column carries no NULL (optionally no empty) values.

    The NULL count is derived as ``COUNT(*) - COUNT(column)`` so it needs
    no engine-specific NULL predicate. The ``include_empty_strings``
    param additionally counts ``''`` values as violations for text
    columns.
    """

    name: ClassVar[str] = "column_not_empty"
    requires_column: ClassVar[bool] = True

    def build_measures(
        self,
        check: DataQualityCheckConfig,
        context: DataQualityContext,
    ) -> list[QualityMeasure]:
        column: str = check.column  # type: ignore[assignment]
        measures = [
            QualityMeasure(
                alias=ROW_COUNT_MEASURE_ALIAS,
                kind=QualityMeasureKinds.ROW_COUNT,
            ),
            QualityMeasure(
                alias=build_non_null_count_alias(column),
                column=column,
                kind=QualityMeasureKinds.NON_NULL_COUNT,
            ),
        ]
        if check.params.get("include_empty_strings", False):
            measures.append(
                QualityMeasure(
                    alias=build_empty_string_count_alias(column),
                    column=column,
                    kind=QualityMeasureKinds.EMPTY_STRING_COUNT,
                ),
            )
        return measures

    def evaluate(
        self,
        check: DataQualityCheckConfig,
        context: DataQualityContext,
        measures: dict[str, Any],
    ) -> DataQualityCheckResult:
        column: str = check.column  # type: ignore[assignment]
        total = measures.get(ROW_COUNT_MEASURE_ALIAS)
        non_null = measures.get(build_non_null_count_alias(column))

        if total is None or non_null is None:
            return DataQualityCheckResult(
                column=column,
                message="Row counts are not available; check skipped",
                rule=self.name,
                severity=check.severity,
                skipped=True,
                status=DataQualityCheckStatus.VALID,
            )

        violations = int(total) - int(non_null)
        if check.params.get("include_empty_strings", False):
            empty_count = measures.get(build_empty_string_count_alias(column))
            violations += int(empty_count or 0)

        is_valid = violations == 0
        # The column lives in the step name and the expectation in the
        # rule name, so neither is repeated in the message or expected.
        message = None if is_valid else f"{violations} empty value(s)"
        return DataQualityCheckResult(
            column=column,
            message=message,
            observed=violations,
            rule=self.name,
            severity=check.severity,
            status=resolve_binary_check_status(is_valid=is_valid),
            violation_count=violations,
        )

    def _validate_params(
        self,
        check: DataQualityCheckConfig,
    ) -> list[str]:
        """Validate the include_empty_strings param when provided."""
        errors = self._validate_param_keys(
            check=check,
            allowed_keys={"include_empty_strings"},
        )
        include_empty_strings = check.params.get("include_empty_strings", False)
        if not isinstance(include_empty_strings, bool):
            errors.append(
                f"Data quality rule '{self.name}' param "
                f"'include_empty_strings' must be a boolean"
            )
        return errors
