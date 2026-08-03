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
    build_not_in_set_count_alias,
)


class ValueInSetRule(DataQualityRule):
    """Check that a column only carries values from an allowed set.

    NULL values are never counted as violations — combine with
    ``column_not_empty`` to also forbid NULLs.
    """

    name: ClassVar[str] = "value_in_set"
    requires_column: ClassVar[bool] = True

    def build_measures(
        self,
        check: DataQualityCheckConfig,
        context: DataQualityContext,
    ) -> list[QualityMeasure]:
        column: str = check.column  # type: ignore[assignment]
        return [
            QualityMeasure(
                alias=build_not_in_set_count_alias(column),
                column=column,
                kind=QualityMeasureKinds.NOT_IN_SET_COUNT,
                values=list(check.params["values"]),
            ),
        ]

    def evaluate(
        self,
        check: DataQualityCheckConfig,
        context: DataQualityContext,
        measures: dict[str, Any],
    ) -> DataQualityCheckResult:
        column: str = check.column  # type: ignore[assignment]
        allowed_values = list(check.params["values"])

        # SUM over an empty table returns NULL, which means zero violations.
        violations = measures.get(build_not_in_set_count_alias(column))
        violations = int(violations) if violations is not None else 0

        is_valid = violations == 0
        # The column lives in the step name and the allowed set in the
        # expected field, so neither is repeated in the message.
        message = None if is_valid else f"{violations} value(s) outside the allowed set"
        return DataQualityCheckResult(
            column=column,
            expected=f"in {allowed_values}",
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
        """Validate the mandatory non-empty values param."""
        errors = self._validate_param_keys(
            check=check,
            allowed_keys={"values"},
        )
        values = check.params.get("values")
        if not isinstance(values, list) or not values:
            errors.append(
                f"Data quality rule '{self.name}' requires a non-empty "
                f"'values' list param"
            )
        return errors
