from typing import Any

from sqlglot import exp

from nld.pydantic import NldBaseModel
from nld.utils import NldStrEnum

ROW_COUNT_MEASURE_ALIAS = "row_count"


class QualityMeasureKinds(NldStrEnum):
    ABOVE_THRESHOLD_COUNT = "ABOVE_THRESHOLD_COUNT"
    BELOW_THRESHOLD_COUNT = "BELOW_THRESHOLD_COUNT"
    DISTINCT_COUNT = "DISTINCT_COUNT"
    EMPTY_STRING_COUNT = "EMPTY_STRING_COUNT"
    MAX_VALUE = "MAX_VALUE"
    MIN_VALUE = "MIN_VALUE"
    NON_NULL_COUNT = "NON_NULL_COUNT"
    NOT_IN_SET_COUNT = "NOT_IN_SET_COUNT"
    ROW_COUNT = "ROW_COUNT"


class QualityMeasure(NldBaseModel):
    """One aggregate to compute on the target for quality evaluation.

    Measures from every check of a flow are merged (deduplicated on
    ``alias``) into a single-scan SELECT so N column checks never cost N
    table scans. Deduplication assumes an alias uniquely identifies the
    measure semantics, so a rule whose parameterized measure could differ
    from another rule's on the same column (e.g. a threshold count with a
    different threshold) must use a rule-specific alias prefix instead of
    the shared helpers. ``threshold``/``exclusive`` only apply to the
    threshold counts and ``values`` only to NOT_IN_SET_COUNT.
    """

    alias: str
    column: str | None = None
    exclusive: bool = False
    kind: str
    threshold: float | None = None
    values: list[Any] | None = None


def build_non_null_count_alias(column: str) -> str:
    return f"nn_{column.lower()}"


def build_distinct_count_alias(column: str) -> str:
    return f"dc_{column.lower()}"


def build_min_value_alias(column: str) -> str:
    return f"min_{column.lower()}"


def build_max_value_alias(column: str) -> str:
    return f"max_{column.lower()}"


def build_below_threshold_count_alias(column: str) -> str:
    return f"blw_{column.lower()}"


def build_above_threshold_count_alias(column: str) -> str:
    return f"abv_{column.lower()}"


def build_empty_string_count_alias(column: str) -> str:
    return f"emp_{column.lower()}"


def build_not_in_set_count_alias(column: str) -> str:
    return f"nis_{column.lower()}"


def _build_conditional_count(condition: exp.Expression) -> exp.Expression:
    """Wrap a boolean condition into a SUM(CASE WHEN ... 1 ELSE 0) count.

    A NULL column value makes the condition non-true, so NULLs are never
    counted as violations by these conditional counts; NULL handling is the
    responsibility of the column_not_empty rule.
    """
    case_expression = exp.Case(
        ifs=[
            exp.If(
                this=condition,
                true=exp.Literal.number("1"),
            ),
        ],
        default=exp.Literal.number("0"),
    )
    return exp.Sum(this=case_expression)


def _build_measure_expression(measure: QualityMeasure) -> exp.Expression:
    """Build the aggregate expression of a single quality measure."""
    column = (
        exp.column(exp.to_identifier(measure.column, quoted=False))
        if measure.column is not None
        else None
    )

    if measure.kind == QualityMeasureKinds.ROW_COUNT:
        return exp.Count(this=exp.Star())

    if column is None:
        raise ValueError(f"Quality measure kind '{measure.kind}' requires a column")

    if measure.kind == QualityMeasureKinds.NON_NULL_COUNT:
        return exp.Count(this=column)
    if measure.kind == QualityMeasureKinds.DISTINCT_COUNT:
        return exp.Count(this=exp.Distinct(expressions=[column]))
    if measure.kind == QualityMeasureKinds.MIN_VALUE:
        return exp.Min(this=column)
    if measure.kind == QualityMeasureKinds.MAX_VALUE:
        return exp.Max(this=column)
    if measure.kind == QualityMeasureKinds.BELOW_THRESHOLD_COUNT:
        if measure.threshold is None:
            raise ValueError(
                "Quality measure kind 'BELOW_THRESHOLD_COUNT' requires a threshold"
            )
        comparison_type = exp.LTE if measure.exclusive else exp.LT
        return _build_conditional_count(
            comparison_type(
                this=column,
                expression=exp.convert(measure.threshold),
            ),
        )
    if measure.kind == QualityMeasureKinds.ABOVE_THRESHOLD_COUNT:
        if measure.threshold is None:
            raise ValueError(
                "Quality measure kind 'ABOVE_THRESHOLD_COUNT' requires a threshold"
            )
        above_comparison_type = exp.GTE if measure.exclusive else exp.GT
        return _build_conditional_count(
            above_comparison_type(
                this=column,
                expression=exp.convert(measure.threshold),
            ),
        )
    if measure.kind == QualityMeasureKinds.EMPTY_STRING_COUNT:
        return _build_conditional_count(
            exp.EQ(
                this=column,
                expression=exp.Literal.string(""),
            ),
        )
    if measure.kind == QualityMeasureKinds.NOT_IN_SET_COUNT:
        if not measure.values:
            raise ValueError(
                "Quality measure kind 'NOT_IN_SET_COUNT' requires a "
                "non-empty values list"
            )
        in_condition = exp.In(
            this=column,
            expressions=[exp.convert(value) for value in measure.values],
        )
        return _build_conditional_count(exp.Not(this=in_condition))

    raise ValueError(f"Unknown quality measure kind '{measure.kind}'")


def build_quality_measures_query(
    table_path: str,
    measures: list[QualityMeasure],
    dialect: str = "postgres",
) -> str:
    """Build the single-scan aggregate SELECT for quality measures.

    Columns are referenced unquoted so they resolve against the case the
    engine folded them to on creation (uppercase on Snowflake, lowercase
    on PostgreSQL); output aliases are quoted so the result column names
    are preserved verbatim and can be read back by their exact lowercase
    key regardless of dialect — the same portability idiom as
    ``build_technical_timestamps_query``.
    """
    select_expressions = [
        exp.Alias(
            this=_build_measure_expression(measure),
            alias=exp.to_identifier(measure.alias, quoted=True),
        )
        for measure in measures
    ]
    query = exp.Select(expressions=select_expressions).from_(table_path)
    return query.sql(dialect=dialect)
