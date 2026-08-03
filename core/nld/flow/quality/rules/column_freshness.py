import datetime
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
    build_max_value_alias,
)
from nld.utils.datetime_util import get_current_datetime


class ColumnFreshnessRule(DataQualityRule):
    """Check that a timestamp column is fresher than a maximum age.

    Only ``MAX(column)`` is computed on the target; the age comparison
    happens in Python so no engine-specific date arithmetic is needed.
    Naive timestamps read from the target are assumed to be UTC.
    """

    name: ClassVar[str] = "column_freshness"
    requires_column: ClassVar[bool] = True

    def build_measures(
        self,
        check: DataQualityCheckConfig,
        context: DataQualityContext,
    ) -> list[QualityMeasure]:
        column: str = check.column  # type: ignore[assignment]
        return [
            QualityMeasure(
                alias=build_max_value_alias(column),
                column=column,
                kind=QualityMeasureKinds.MAX_VALUE,
            ),
        ]

    def evaluate(
        self,
        check: DataQualityCheckConfig,
        context: DataQualityContext,
        measures: dict[str, Any],
    ) -> DataQualityCheckResult:
        column: str = check.column  # type: ignore[assignment]
        max_age_hours = float(check.params["max_age_hours"])
        raw_observed = measures.get(build_max_value_alias(column))
        observed = self._coerce_to_utc_datetime(raw_observed)
        threshold = get_current_datetime() - datetime.timedelta(
            hours=max_age_hours,
        )

        if raw_observed is not None and observed is None:
            return DataQualityCheckResult(
                column=column,
                message=(
                    f"Maximum value '{raw_observed}' is not a timestamp; check skipped"
                ),
                observed=raw_observed,
                rule=self.name,
                severity=check.severity,
                skipped=True,
                status=DataQualityCheckStatus.VALID,
            )

        is_valid = observed is not None and observed >= threshold
        # The column lives in the step name, so it is not repeated here.
        message = (
            None
            if is_valid
            else (
                f"Latest timestamp "
                f"{observed if observed is not None else '(no rows)'} is "
                f"older than {max_age_hours} hour(s)"
            )
        )
        return DataQualityCheckResult(
            column=column,
            expected=f">= {threshold.isoformat()}",
            message=message,
            observed=raw_observed,
            rule=self.name,
            severity=check.severity,
            status=resolve_binary_check_status(is_valid=is_valid),
        )

    @staticmethod
    def _coerce_to_utc_datetime(value: Any) -> datetime.datetime | None:
        """Coerce an engine-returned value into an aware UTC datetime."""
        if value is None:
            return None
        coerced: datetime.datetime | None = None
        if isinstance(value, datetime.datetime):
            coerced = value
        elif isinstance(value, datetime.date):
            coerced = datetime.datetime.combine(
                value,
                datetime.time.min,
            )
        elif isinstance(value, str):
            try:
                coerced = datetime.datetime.fromisoformat(value)
            except ValueError:
                return None
        if coerced is None:
            return None
        if coerced.tzinfo is None:
            return coerced.replace(tzinfo=datetime.UTC)
        return coerced.astimezone(datetime.UTC)

    def _validate_params(
        self,
        check: DataQualityCheckConfig,
    ) -> list[str]:
        """Validate the mandatory positive max_age_hours param."""
        errors = self._validate_param_keys(
            check=check,
            allowed_keys={"max_age_hours"},
        )
        if "max_age_hours" not in check.params:
            errors.append(
                f"Data quality rule '{self.name}' requires a numeric "
                f"'max_age_hours' param"
            )
            return errors
        max_age_hours = check.params["max_age_hours"]
        if (
            not isinstance(max_age_hours, int | float)
            or isinstance(max_age_hours, bool)
            or max_age_hours <= 0
        ):
            errors.append(
                f"Data quality rule '{self.name}' param 'max_age_hours' "
                f"must be a positive number"
            )
        return errors
