import abc
from typing import Any, ClassVar

from nld.exceptions import NotImplementedMethodException
from nld.flow.quality.models.config import DataQualityCheckConfig
from nld.flow.quality.models.context import DataQualityContext
from nld.flow.quality.models.result import DataQualityCheckResult
from nld.flow.quality.sql_measures import QualityMeasure
from nld.utils.mixin import NldMixIn


class DataQualityRule(NldMixIn, abc.ABC):
    """Base class of a data quality rule evaluated on a flow target.

    A rule contributes aggregate measures to the single-scan measurement
    query through ``build_measures`` and turns the measured values into a
    ``DataQualityCheckResult`` through ``evaluate``. Rules never issue SQL
    themselves — the service builds and runs one combined query — so a
    rule stays engine-agnostic by construction.
    """

    name: ClassVar[str] = ""
    requires_baseline: ClassVar[bool] = False
    requires_column: ClassVar[bool] = False

    @abc.abstractmethod
    def build_measures(
        self,
        check: DataQualityCheckConfig,
        context: DataQualityContext,
    ) -> list[QualityMeasure]:
        """Return the aggregate measures this check needs on the target."""
        raise NotImplementedMethodException(
            obj_class=type(self),
            method_name="build_measures",
        )

    @abc.abstractmethod
    def evaluate(
        self,
        check: DataQualityCheckConfig,
        context: DataQualityContext,
        measures: dict[str, Any],
    ) -> DataQualityCheckResult:
        """Evaluate the check from the measured values."""
        raise NotImplementedMethodException(
            obj_class=type(self),
            method_name="evaluate",
        )

    def validate_check(
        self,
        check: DataQualityCheckConfig,
    ) -> list[str]:
        """Validate a check configuration; returns human-readable errors."""
        errors: list[str] = []
        if self.requires_column and check.column is None and not check.columns:
            errors.append(
                f"Data quality rule '{self.name}' requires a 'column' "
                f"(or 'columns') on the check"
            )
        errors.extend(self._validate_params(check=check))
        return errors

    def _validate_params(
        self,
        check: DataQualityCheckConfig,
    ) -> list[str]:
        """Validate the rule-specific params; empty by default."""
        return self._validate_param_keys(
            check=check,
            allowed_keys=set(),
        )

    def _validate_param_keys(
        self,
        check: DataQualityCheckConfig,
        allowed_keys: set[str],
    ) -> list[str]:
        """Reject unknown param keys so YAML typos surface as errors."""
        unknown_keys = set(check.params.keys()) - allowed_keys
        if not unknown_keys:
            return []
        return [
            f"Data quality rule '{self.name}' does not accept params "
            f"{sorted(unknown_keys)}; allowed params: {sorted(allowed_keys)}"
        ]
