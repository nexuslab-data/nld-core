from pydantic import Field

from nld.pydantic import NldBaseModel, NldNamedBaseModel

from .audit_distribution import AuditDistribution


class AuditColumnCoverage(NldBaseModel):
    """Measured coverage and value-range statistics for a single column.

    Example YAML:
        non_null: 217
        pct: 17.3
        distinct: 95
        min: 6
        max: 70000000
    """

    non_null: int | None = Field(
        default=None,
        description="Number of non-null values",
    )
    pct: float | None = Field(
        default=None,
        description="Coverage percentage (non-null over total rows)",
    )
    distinct: int | None = Field(
        default=None,
        description="Number of distinct values",
    )
    min: str | int | float | None = Field(
        default=None,
        description="Minimum value (numeric or temporal columns)",
    )
    max: str | int | float | None = Field(
        default=None,
        description="Maximum value (numeric or temporal columns)",
    )


class AuditColumn(NldNamedBaseModel):
    """A single audited column: intrinsic info, coverage and value distribution.

    The ``name`` defaults to the dict key when used inside
    ``StructureAudit.columns``.

    Example YAML:
        contract_type:
            data_type: CHARACTER VARYING
            nullable: false
            primary_key: false
            coverage: { non_null: 1251, pct: 100.0, distinct: 8 }
            distribution:
                top_n: 10
                truncated: false
                values:
                    - { value: full_time, count: 884, pct: 70.7 }
    """

    data_type: str | None = Field(
        default=None,
        description="Database data type of the column",
    )
    nullable: bool | None = Field(
        default=None,
        description="Whether the column is nullable in the structure",
    )
    primary_key: bool = Field(
        default=False,
        description="Whether the column is part of the structure's primary key",
    )
    coverage: AuditColumnCoverage = Field(
        default_factory=AuditColumnCoverage,
        description="Measured coverage and value-range statistics",
    )
    distribution: AuditDistribution | None = Field(
        default=None,
        description="Value distribution of the column (top_n buckets)",
    )
    notes: str | None = Field(
        default=None,
        description="Free-text remarks about the column",
    )
