from pydantic import Field

from nld.pydantic import NldBaseModel

DEFAULT_TOP_N = 10


class AuditDistributionValue(NldBaseModel):
    """A single value bucket in a column value distribution.

    Example YAML:
        { value: full_time, count: 884, pct: 70.7 }
    """

    value: str | int | float | bool | None = Field(
        description="The distinct value (null when counting missing values)",
    )
    count: int = Field(
        description="Number of rows holding this value",
    )
    pct: float | None = Field(
        default=None,
        description="Share of rows holding this value",
    )


class AuditDistribution(NldBaseModel):
    """The value distribution of a column, capped at ``top_n`` values.

    Nested under an ``AuditColumn`` (one distribution per column). ``truncated``
    flags that the column has more distinct values than were listed (i.e. the
    column's distinct count exceeds top_n).

    Example YAML:
        top_n: 10
        truncated: false
        values:
            - { value: full_time, count: 884, pct: 70.7 }
            - { value: internship, count: 171, pct: 13.7 }
    """

    top_n: int = Field(
        default=DEFAULT_TOP_N,
        description="Maximum number of value buckets listed",
    )
    truncated: bool = Field(
        default=False,
        description="True when distinct values exceed top_n (list is capped)",
    )
    values: list[AuditDistributionValue] = Field(
        default=[],
        description="Value buckets, ordered by count descending",
    )
