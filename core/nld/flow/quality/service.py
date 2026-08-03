from typing import Any

import nld.flow.quality.rules  # noqa: F401  — seeds the built-in rules
from nld.flow.exceptions import FlowException
from nld.flow.quality.models.config import (
    DataQualityCheckConfig,
    DataQualityChecksConfig,
)
from nld.flow.quality.models.context import DataQualityContext
from nld.flow.quality.models.result import DataQualityCheckResult
from nld.flow.quality.registry import get_data_quality_rule_registry
from nld.flow.quality.sql_measures import (
    QualityMeasure,
    build_quality_measures_query,
)
from nld.structure import Structure
from nld.utils.mixin import NldMixIn


def resolve_effective_checks(
    quality_checks: DataQualityChecksConfig | None,
) -> list[DataQualityCheckConfig]:
    """Resolve the checks to evaluate for one flow target.

    Checks are configured at flow level only: without a ``quality_checks``
    block (or with the block disabled) nothing runs. Declared checks are
    expanded per column and deduplicated per (rule, column) pair — the
    last declaration wins and ``enabled: false`` drops the pair.
    """
    if quality_checks is None or not quality_checks.enabled:
        return []

    merged: dict[tuple[str, str | None], DataQualityCheckConfig] = {}
    _merge_expanded_checks(
        merged=merged,
        checks=quality_checks.checks,
    )
    return list(merged.values())


def _merge_expanded_checks(
    merged: dict[tuple[str, str | None], DataQualityCheckConfig],
    checks: list[DataQualityCheckConfig],
) -> None:
    """Overlay checks into the merge dict, one entry per (rule, column).

    Multi-column checks are expanded into per-column copies here so the
    dedup matching and the later evaluation always operate on
    single-column configurations. A disabled check removes the matching
    entry instead of adding one.
    """
    for check in checks:
        for column in check.get_target_columns():
            merge_key = (check.rule, column.lower() if column else None)
            if not check.enabled:
                merged.pop(merge_key, None)
                continue
            merged[merge_key] = check.model_copy(
                update={"column": column, "columns": None},
            )


def validate_quality_checks(
    quality_checks: DataQualityChecksConfig | None,
    target_structure: Structure | None,
) -> list[str]:
    """Validate a quality_checks block; returns human-readable errors.

    Rule names are checked against the registry and the rule-specific
    param validation runs per check. Column existence is only validated
    when the target structure is resolvable, so a flow without a
    target_structure still gets its rule and param errors.
    """
    if quality_checks is None:
        return []

    errors: list[str] = []
    registry = get_data_quality_rule_registry()
    structure_columns = _resolve_structure_columns(target_structure)

    for check in quality_checks.checks:
        if not registry.has(name=check.rule):
            errors.append(
                f"Unknown data quality rule '{check.rule}'; available "
                f"rules: {registry.names()}"
            )
            continue
        rule = registry.get(name=check.rule)
        errors.extend(rule.validate_check(check=check))
        if structure_columns is None:
            continue
        for column in check.get_target_columns():
            if column is not None and column.lower() not in structure_columns:
                errors.append(
                    f"Data quality check '{check.rule}' references column "
                    f"'{column}' which does not exist on the target "
                    f"structure"
                )
    return errors


def _resolve_structure_columns(
    target_structure: Structure | None,
) -> set[str] | None:
    """Lowercased column names of the structure, None when unavailable."""
    if target_structure is None:
        return None
    return {field.name.lower() for field in target_structure.get_all_fields()}


class FlowDataQualityService(NldMixIn):
    """Evaluates the resolved data quality checks on one flow target.

    The service merges the measures of every check into one single-scan
    aggregate query, executes it through the target connector, and lets
    each rule evaluate its result from the measured values.

    The service owns the target context for the whole run: the task
    resolves it once and hands it over, None when the task has no SQL
    target to check.
    """

    def __init__(
        self,
        checks: list[DataQualityCheckConfig],
        context: DataQualityContext | None,
    ) -> None:
        super().__init__()
        self._context = context
        self._registry = get_data_quality_rule_registry()
        self.checks = checks

    def has_checks(self) -> bool:
        return len(self.checks) > 0

    def requires_baseline(self) -> bool:
        """Whether any resolved check needs a pre-write row count."""
        return any(
            self._registry.get(name=check.rule).requires_baseline
            for check in self.checks
        )

    def capture_baseline(self) -> int | None:
        """Capture the pre-write COUNT(*) on the target context.

        Only runs when a resolved check needs a baseline and a target
        context is bound; the count is stored on the context so the
        rules read it at evaluation time. Returns the captured count for
        observability.
        """
        if self._context is None or not self.requires_baseline():
            return None
        self._context.baseline_row_count = int(
            self._context.connector.get_row_count(self._context.table_path),
        )
        return self._context.baseline_row_count

    def log_check_results(
        self,
        results: list[DataQualityCheckResult],
    ) -> None:
        """Log every violated or skipped check result."""
        for result in results:
            if not result.is_valid:
                self.log_warn(
                    f"Data quality check violated "
                    f"({result.status}/{result.severity}): {result.message}",
                )
            elif result.skipped:
                self.log_info(f"Data quality check skipped: {result.message}")

    def run_checks_on_target(self) -> list[DataQualityCheckResult]:
        """Measure the target once and evaluate every resolved check.

        Nothing runs without resolved checks or without a bound target
        context, so a task with no SQL target simply yields no result.
        """
        if self._context is None or not self.has_checks():
            return []

        measured_values = self._measure(context=self._context)
        results: list[DataQualityCheckResult] = []
        for check in self.checks:
            rule = self._registry.get(name=check.rule)
            results.append(
                rule.evaluate(
                    check=check,
                    context=self._context,
                    measures=measured_values,
                ),
            )
        return results

    def _measure(self, context: DataQualityContext) -> dict[str, Any]:
        """Run the combined measurement query and return values by alias."""
        measures = self._collect_measures(context=context)
        if not measures:
            return {}

        query = build_quality_measures_query(
            table_path=context.table_path,
            measures=measures,
            dialect=getattr(context.connector, "sqlglot_dialect", "postgres"),
        )
        query_result = context.connector.execute_query(query)
        if query_result.failed():
            raise FlowException(
                message=(
                    f"Data quality measurement query failed on "
                    f"{context.table_path}: {query_result.get_error_message()}"
                ),
            )

        records = query_result.get_result_records()
        if not records:
            return {}
        # Engines disagree on result-key casing; aliases are lowercase by
        # construction so a lowercased lookup is always safe.
        return {str(key).lower(): value for key, value in records[0].items()}

    def _collect_measures(
        self,
        context: DataQualityContext,
    ) -> list[QualityMeasure]:
        """Collect the measures of every check, deduplicated on alias."""
        measures_by_alias: dict[str, QualityMeasure] = {}
        for check in self.checks:
            rule = self._registry.get(name=check.rule)
            for measure in rule.build_measures(
                check=check,
                context=context,
            ):
                measures_by_alias.setdefault(measure.alias, measure)
        return list(measures_by_alias.values())
