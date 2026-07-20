from datetime import date, datetime

from pydantic import ConfigDict, Field, field_validator

from nld.pydantic import NldBaseModel


def _coerce_date_to_iso(value: object) -> object:
    """Normalize YAML-parsed date/datetime values to ISO strings."""
    if isinstance(value, date | datetime):
        return value.isoformat()
    return value


def _coerce_to_iso_timestamp(value: object) -> object:
    """Normalize a value to an ISO 8601 timestamp string.

    A YAML-parsed ``datetime`` is rendered with its time component; a bare
    ``date`` is widened to midnight so the field always reads as a timestamp.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day).isoformat()
    return value


class AuditSampling(NldBaseModel):
    """Whether the audit figures were computed on a sample or the full table.

    When ``sampled`` is False the audit covers every row and the remaining
    fields are irrelevant. When True, the optional fields describe how the
    sample was drawn.

    Example YAML:
        sampled: true
        method: tablesample_system
        sample_size: 10000
        fraction: 0.1
    """

    sampled: bool = Field(
        default=False,
        description="True when the figures are based on a sample, not the full table",
    )
    method: str | None = Field(
        default=None,
        description="How the sample was drawn (e.g. random, tablesample_system)",
    )
    sample_size: int | None = Field(
        default=None,
        description="Number of rows examined when sampled",
    )
    fraction: float | None = Field(
        default=None,
        description="Sampled fraction of the table, between 0 and 1",
    )


class AuditDateCoverage(NldBaseModel):
    """The time span the audited data covers, when pertinent.

    The span is measured on the field carrying ``field_characterisation`` (a
    field characterisation name, e.g. ``rec_source_extraction_tst``), not a
    hard-coded column name. Omit the whole block for structures that have no
    meaningful date dimension.

    Example YAML:
        field_characterisation: rec_source_extraction_tst
        from: 2025-10-19
        to: 2026-04-01
    """

    model_config = ConfigDict(populate_by_name=True)

    field_characterisation: str | None = Field(
        default=None,
        description=(
            "Field characterisation the span is measured on "
            "(e.g. rec_source_extraction_tst)"
        ),
    )
    from_: str | None = Field(
        default=None,
        alias="from",
        description="Earliest date covered (ISO date)",
    )
    to: str | None = Field(
        default=None,
        description="Latest date covered (ISO date)",
    )

    @field_validator("from_", "to", mode="before")
    @classmethod
    def _normalize_dates(cls, value: object) -> object:
        return _coerce_date_to_iso(value)


class AuditMetadata(NldBaseModel):
    """Provenance and high-level facts about an audit run.

    Example YAML:
        audited_at: 2026-04-04T00:00:00
        row_count: 1251
        sampling:
            sampled: false
        date_coverage:
            field_characterisation: rec_source_extraction_tst
            from: 2025-10-19
            to: 2026-04-01
    """

    audited_at: str | None = Field(
        default=None,
        description="ISO 8601 timestamp when the audit was produced",
    )
    row_count: int | None = Field(
        default=None,
        description="Total number of rows in the audited structure",
    )
    sampling: AuditSampling = Field(
        default_factory=AuditSampling,
        description="Sampling information for the audit figures",
    )
    date_coverage: AuditDateCoverage | None = Field(
        default=None,
        description="Time span the audited data covers, when pertinent",
    )

    @field_validator("audited_at", mode="before")
    @classmethod
    def _normalize_audited_at(cls, value: object) -> object:
        return _coerce_to_iso_timestamp(value)
