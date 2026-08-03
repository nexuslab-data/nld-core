from typing import Any

from pydantic import ConfigDict, Field, field_validator, model_validator

from nld.misc import FindingSeverity
from nld.pydantic import NldBaseModel

# Quality-specific escalation above the FindingSeverity vocabulary: a
# blocking violation is the only one that fails the flow execution.
BLOCKING_CHECK_SEVERITY = "blocking"

ALLOWED_CHECK_SEVERITIES: list[str] = [
    BLOCKING_CHECK_SEVERITY,
    FindingSeverity.ERROR,
    FindingSeverity.WARNING,
]


class DataQualityCheckConfig(NldBaseModel):
    """Configuration of a single data quality check on a flow target.

    A check references a rule by name and optionally targets one column
    (``column``) or several (``columns``); a check declared with several
    columns is evaluated once per column. ``severity`` escalates in three
    levels: a ``warning`` violation records a WARNING step, an ``error``
    violation a FAILED step — neither fails the flow execution — and a
    ``blocking`` violation records a FAILED step and marks the whole
    execution FAILED once every check result is recorded. ``enabled:
    false`` keeps the check declared but skips its evaluation.
    """

    model_config = ConfigDict(extra="forbid")

    column: str | None = None
    columns: list[str] | None = None
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)
    rule: str
    severity: str = FindingSeverity.ERROR

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, value: Any) -> Any:
        """Lowercase the severity so YAML capitalisation does not matter."""
        if isinstance(value, str):
            return value.lower()
        return value

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, value: str) -> str:
        """Reject severities outside the error/warning vocabulary."""
        if value not in ALLOWED_CHECK_SEVERITIES:
            raise ValueError(
                f"Invalid check severity '{value}': "
                f"must be one of {ALLOWED_CHECK_SEVERITIES}"
            )
        return value

    @model_validator(mode="after")
    def validate_column_and_columns_exclusive(self) -> "DataQualityCheckConfig":
        """Ensure column and columns are not both set."""
        if self.column is not None and self.columns is not None:
            raise ValueError(
                "'column' and 'columns' are mutually exclusive on a data "
                "quality check. Use 'column' for a single column or "
                "'columns' for several, but not both."
            )
        return self

    def get_target_columns(self) -> list[str | None]:
        """Return the columns this check targets; [None] for table-level."""
        if self.columns:
            return list(self.columns)
        return [self.column]


class DataQualityChecksConfig(NldBaseModel):
    """The ``quality_checks`` block of a flow definition.

    Data quality checks are configured at flow level only: no check runs
    without this block, and ``enabled: false`` turns the whole step off
    without deleting the declared checks.
    """

    model_config = ConfigDict(extra="forbid")

    checks: list[DataQualityCheckConfig] = Field(default_factory=list)
    enabled: bool = True
