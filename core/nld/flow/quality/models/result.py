from typing import Any

from nld.flow.quality.models.config import BLOCKING_CHECK_SEVERITY
from nld.misc import FindingSeverity
from nld.pydantic import NldBaseModel


class DataQualityCheckStatus:
    """Outcome levels a rule can report for one evaluated check."""

    ERROR = "error"
    VALID = "valid"
    WARNING = "warning"


def resolve_binary_check_status(is_valid: bool) -> str:
    """Map a pass/fail rule outcome onto the three-level status."""
    return DataQualityCheckStatus.VALID if is_valid else DataQualityCheckStatus.ERROR


class DataQualityCheckResult(NldBaseModel):
    """Outcome of one evaluated data quality check.

    ``status`` is what the rule found: VALID when the data matches the
    expectation, ERROR when it does not, and WARNING for the middle
    ground a rule may want to report — most rules are binary and only
    ever emit VALID or ERROR, through ``resolve_binary_check_status``.
    ``severity`` is the level the check was declared with and decides how
    the flow reacts to a non-valid status: a warning severity keeps an
    error status at step level, an error severity fails the step, and a
    blocking severity fails the whole execution. A WARNING status never
    fails a step, whatever the declared severity.

    ``skipped`` marks a check that could not be evaluated (e.g. a row-growth
    check without a captured baseline); a skipped check is reported as
    valid so it never degrades the execution status, but the skip reason
    is kept in ``message`` for diagnosability. ``violation_count`` is the
    standardized number of rows not matching the check, persisted with the
    step and rendered in the CLI verdict; rules whose violations are not
    row-scoped (e.g. freshness) leave it unset.
    """

    column: str | None = None
    expected: Any = None
    message: str | None = None
    observed: Any = None
    rule: str
    severity: str = FindingSeverity.ERROR
    skipped: bool = False
    status: str
    violation_count: int | None = None

    @property
    def is_valid(self) -> bool:
        """Whether the check found nothing to report."""
        return self.status == DataQualityCheckStatus.VALID

    @property
    def is_blocking(self) -> bool:
        """Whether this outcome must fail the whole flow execution."""
        return (
            self.status == DataQualityCheckStatus.ERROR
            and self.severity == BLOCKING_CHECK_SEVERITY
        )

    @property
    def is_step_failure(self) -> bool:
        """Whether this outcome must record a FAILED step.

        An error status is held at warning level when the check was
        declared with the warning severity, and a warning status never
        fails a step whatever the declared severity.
        """
        return (
            self.status == DataQualityCheckStatus.ERROR
            and self.severity != FindingSeverity.WARNING
        )

    def get_step_name(self) -> str:
        """Build the unique execution step name for this check."""
        if self.column is None:
            return f"Data Quality - {self.rule}"
        return f"Data Quality - {self.rule} - {self.column}"

    def to_step_metadata(self) -> dict[str, Any]:
        """Build the step metadata payload persisted with the check step."""
        return self.model_dump(
            mode="json",
            exclude_none=True,
        )
