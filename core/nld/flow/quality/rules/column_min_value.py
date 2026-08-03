from typing import Any, ClassVar

from nld.flow.quality.models.config import DataQualityCheckConfig
from nld.flow.quality.models.context import DataQualityContext
from nld.flow.quality.models.result import (
    DataQualityCheckResult,
    resolve_binary_check_status,
)
from nld.flow.quality.rules.base import DataQualityRule
from nld.flow.quality.sql_measures import (
    QualityMeasure,
    QualityMeasureKinds,
    build_below_threshold_count_alias,
    build_min_value_alias,
)


class ColumnMinValueRule(DataQualityRule):
    """Check that a numeric column stays above a threshold.

    The ``min`` param is the threshold; ``exclusive: true`` requires
    strictly greater values (``> min`` instead of ``>= min``). NULL
    values are never counted as violations — combine with
    ``column_not_empty`` to also forbid NULLs.
    """

    name: ClassVar[str] = "column_min_value"
    requires_column: ClassVar[bool] = True

    def build_measures(
        self,
        check: DataQualityCheckConfig,
        context: DataQualityContext,
    ) -> list[QualityMeasure]:
        column: str = check.column  # type: ignore[assignment]
        return [
            QualityMeasure(
                alias=build_min_value_alias(column),
                column=column,
                kind=QualityMeasureKinds.MIN_VALUE,
            ),
            QualityMeasure(
                alias=build_below_threshold_count_alias(column),
                column=column,
                exclusive=bool(check.params.get("exclusive", False)),
                kind=QualityMeasureKinds.BELOW_THRESHOLD_COUNT,
                threshold=float(check.params["min"]),
            ),
        ]

    def evaluate(
        self,
        check: DataQualityCheckConfig,
        context: DataQualityContext,
        measures: dict[str, Any],
    ) -> DataQualityCheckResult:
        column: str = check.column  # type: ignore[assignment]
        exclusive = bool(check.params.get("exclusive", False))
        threshold = check.params["min"]
        comparator = ">" if exclusive else ">="

        # SUM over an empty table returns NULL, which means zero violations.
        violations = measures.get(build_below_threshold_count_alias(column))
        violations = int(violations) if violations is not None else 0
        min_observed = measures.get(build_min_value_alias(column))

        is_valid = violations == 0
        # The column lives in the step name and the observed minimum in
        # the observed field, so neither is repeated in the message.
        message = (
            None if is_valid else f"{violations} value(s) not {comparator} {threshold}"
        )
        return DataQualityCheckResult(
            column=column,
            expected=f"{comparator} {threshold}",
            message=message,
            observed=min_observed,
            rule=self.name,
            severity=check.severity,
            status=resolve_binary_check_status(is_valid=is_valid),
            violation_count=violations,
        )

    def _validate_params(
        self,
        check: DataQualityCheckConfig,
    ) -> list[str]:
        """Validate the mandatory numeric min and optional exclusive params."""
        errors = self._validate_param_keys(
            check=check,
            allowed_keys={"exclusive", "min"},
        )
        if "min" not in check.params:
            errors.append(
                f"Data quality rule '{self.name}' requires a numeric 'min' param"
            )
        elif not isinstance(check.params["min"], int | float) or isinstance(
            check.params["min"],
            bool,
        ):
            errors.append(
                f"Data quality rule '{self.name}' param 'min' must be a number"
            )
        exclusive = check.params.get("exclusive", False)
        if not isinstance(exclusive, bool):
            errors.append(
                f"Data quality rule '{self.name}' param 'exclusive' must be a boolean"
            )
        return errors
