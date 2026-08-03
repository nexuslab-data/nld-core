from nld.flow.quality.registry import get_data_quality_rule_registry

from .base import DataQualityRule
from .column_freshness import ColumnFreshnessRule
from .column_min_value import ColumnMinValueRule
from .column_not_empty import ColumnNotEmptyRule
from .column_unique import ColumnUniqueRule
from .row_count_growth import RowCountGrowthRule
from .value_in_set import ValueInSetRule

BUILTIN_DATA_QUALITY_RULE_CLASSES: list[type[DataQualityRule]] = [
    ColumnFreshnessRule,
    ColumnMinValueRule,
    ColumnNotEmptyRule,
    ColumnUniqueRule,
    RowCountGrowthRule,
    ValueInSetRule,
]


def _register_builtins() -> None:
    registry = get_data_quality_rule_registry()
    for rule_class in BUILTIN_DATA_QUALITY_RULE_CLASSES:
        if not registry.has(name=rule_class.name):
            registry.register(rule=rule_class())


_register_builtins()

__all__ = [
    "BUILTIN_DATA_QUALITY_RULE_CLASSES",
    "ColumnFreshnessRule",
    "ColumnMinValueRule",
    "ColumnNotEmptyRule",
    "ColumnUniqueRule",
    "DataQualityRule",
    "RowCountGrowthRule",
    "ValueInSetRule",
]
