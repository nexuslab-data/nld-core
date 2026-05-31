import abc
from collections.abc import Callable
from typing import Any

from nld.connector.base.connector import SQLDataConnector
from nld.connector.base.query import QueryExecResult
from nld.flow.seed.seed_file_resolver import load_seed_file_content
from nld.flow.utils.flow_update_strategy import FlowUpdateStrategies
from nld.structure import Structure


class SeedWriteStrategy(abc.ABC):
    """Abstract base class for seed write strategies.

    Seed strategies operate on a CSV seed file, loading it and applying
    the appropriate DML operations on the target connector.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """The strategy name matching the FlowUpdateStrategies value."""

    @property
    @abc.abstractmethod
    def requires_target_structure(self) -> bool:
        """Whether this strategy requires a resolved target structure."""

    @abc.abstractmethod
    def execute(
        self,
        connector: SQLDataConnector[Any],
        table_path: str,
        seed_file_path: str,
        target_structure: Structure | None = None,
    ) -> list[QueryExecResult]:
        """Execute the write strategy from the seed file.

        Args:
            connector: the SQL connector to use for execution.
            table_path: fully qualified target table path.
            seed_file_path: absolute path to the CSV seed file.
            target_structure: resolved target structure (required by
                some strategies for column validation and PK resolution).

        Returns:
            A list of QueryExecResult, one per connector call.
            On failure, the list is returned early with the failed
            result as the last element.
        """

    def _load_rows(
        self,
        seed_file_path: str,
    ) -> list[dict[str, str]]:
        """Load CSV rows from the seed file."""
        return load_seed_file_content(seed_file_path)

    @staticmethod
    def _rows_to_tuples(
        rows: list[dict[str, str]],
    ) -> tuple[list[str], list[tuple[Any, ...]]]:
        """Convert list of row dicts to column list and tuple rows."""
        column_list = list(rows[0].keys())
        tuple_rows = [tuple(row[col] for col in column_list) for row in rows]
        return column_list, tuple_rows

    def _validate_columns(
        self,
        rows: list[dict[str, Any]],
        target_structure: Structure,
    ) -> None:
        """Raise ValueError if CSV columns do not match structure fields.

        Both the CSV headers and the structure field names must be
        identical sets. Extra or missing columns are rejected to
        prevent silent data mismatches.
        """
        csv_columns = set(rows[0].keys()) if rows else set()
        structure_columns = set(target_structure.get_field_names())

        if csv_columns != structure_columns:
            missing = structure_columns - csv_columns
            extra = csv_columns - structure_columns
            parts = []
            if missing:
                parts.append(f"missing from CSV: {sorted(missing)}")
            if extra:
                parts.append(f"extra in CSV: {sorted(extra)}")
            raise ValueError(
                "CSV columns do not match structure fields. " + "; ".join(parts)
            )

    def _assert_table_exists(
        self,
        connector: SQLDataConnector[Any],
        table_path: str,
    ) -> None:
        """Raise if the target table does not exist.

        Seed flows expect the table to be created beforehand via
        ``nld structure deploy``. This guard surfaces a clear error
        message when that step was skipped.
        """
        if not connector.does_object_exist(table_path):
            raise ValueError(
                f"Table {table_path} does not exist. "
                f"Please deploy the structure first by running: "
                f"nld structure deploy --namespace <namespace> "
                f"--name <name>"
            )

    def _get_primary_key_columns(
        self,
        target_structure: Structure,
    ) -> list[str]:
        """Extract primary key column names from the target structure."""
        if not target_structure.has_primary_key():
            raise ValueError(
                "target_structure must have a primary key defined for UPSERT strategy"
            )
        return [field.name for field in target_structure.get_primary_key_fields()]


_VALID_SEED_STRATEGY_NAMES = [
    FlowUpdateStrategies.OVERWRITE,
    FlowUpdateStrategies.INSERT,
    FlowUpdateStrategies.UPSERT,
]


_SEED_STRATEGY_MODULE_MAP: dict[str, str] = {
    "bigquery": "nld.flow.seed.connector.bigquery",
    "duckdb": "nld.flow.seed.connector.duckdb",
    "postgresql": "nld.flow.seed.connector.postgresql",
    "snowflake": "nld.flow.seed.connector.snowflake",
}


def get_seed_write_strategy(
    strategy_name: str,
    connector: SQLDataConnector[Any],
) -> SeedWriteStrategy:
    """Get the seed write strategy for the given strategy name and connector.

    Dispatches to the appropriate connector-specific strategy by
    dynamically importing the module registered for the connector type.

    Args:
        strategy_name: the strategy name (OVERWRITE, INSERT, or UPSERT).
        connector: the target SQL connector used for type dispatch.

    Returns:
        The corresponding SeedWriteStrategy instance.

    Raises:
        ValueError: if the strategy name is not supported for seeds.
        ValueError: if the connector type is not supported.
    """
    from importlib import import_module

    normalized_name = strategy_name.upper()
    if normalized_name not in _VALID_SEED_STRATEGY_NAMES:
        raise ValueError(
            f"Unknown seed write strategy: '{strategy_name}'. "
            f"Valid strategies: {_VALID_SEED_STRATEGY_NAMES}"
        )

    connector_type = connector.connection_wrapper.type
    module_path = _SEED_STRATEGY_MODULE_MAP.get(connector_type)
    if module_path is None:
        raise ValueError(
            f"Seed write strategies are not supported for "
            f"connector type: '{connector_type}'. "
            f"Supported types: {sorted(_SEED_STRATEGY_MODULE_MAP.keys())}"
        )

    mod = import_module(module_path)
    get_strategy_fn: Callable[[str], SeedWriteStrategy] = mod.get_seed_strategy
    return get_strategy_fn(normalized_name)
