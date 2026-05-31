from typing import Any

from nld.connector.base.connector import SQLDataConnector
from nld.connector.base.query import QueryExecResult
from nld.flow.seed.seed_write_strategy import SeedWriteStrategy
from nld.flow.utils.flow_update_strategy import FlowUpdateStrategies
from nld.structure import Structure


class BigQuerySeedOverwriteStrategy(SeedWriteStrategy):
    """TRUNCATE TABLE + bulk INSERT rows for BigQuery."""

    @property
    def name(self) -> str:
        return FlowUpdateStrategies.OVERWRITE

    @property
    def requires_target_structure(self) -> bool:
        return True

    def execute(
        self,
        connector: SQLDataConnector[Any],
        table_path: str,
        seed_file_path: str,
        target_structure: Structure | None = None,
    ) -> list[QueryExecResult]:
        if target_structure is None:
            raise ValueError("target_structure is required for this strategy")
        results: list[QueryExecResult] = []

        self._assert_table_exists(connector=connector, table_path=table_path)

        rows = self._load_rows(seed_file_path)
        self._validate_columns(rows=rows, target_structure=target_structure)

        truncate_result = connector.truncate_table(table_path)
        results.append(truncate_result)
        if truncate_result.failed():
            return results

        column_list, tuple_rows = self._rows_to_tuples(rows)
        batch_results = connector.bulk_insert_into(
            table_path=table_path,
            rows=tuple_rows,
            column_list=column_list,
        )
        results.extend(batch_results)

        return results


class BigQuerySeedInsertStrategy(SeedWriteStrategy):
    """Bulk INSERT rows for BigQuery."""

    @property
    def name(self) -> str:
        return FlowUpdateStrategies.INSERT

    @property
    def requires_target_structure(self) -> bool:
        return True

    def execute(
        self,
        connector: SQLDataConnector[Any],
        table_path: str,
        seed_file_path: str,
        target_structure: Structure | None = None,
    ) -> list[QueryExecResult]:
        if target_structure is None:
            raise ValueError("target_structure is required for this strategy")

        self._assert_table_exists(connector=connector, table_path=table_path)

        rows = self._load_rows(seed_file_path)
        self._validate_columns(rows=rows, target_structure=target_structure)

        column_list, tuple_rows = self._rows_to_tuples(rows)
        return connector.bulk_insert_into(
            table_path=table_path,
            rows=tuple_rows,
            column_list=column_list,
        )


class BigQuerySeedUpsertStrategy(SeedWriteStrategy):
    """Bulk UPSERT rows — insert or update on PK conflict for BigQuery."""

    @property
    def name(self) -> str:
        return FlowUpdateStrategies.UPSERT

    @property
    def requires_target_structure(self) -> bool:
        return True

    def execute(
        self,
        connector: SQLDataConnector[Any],
        table_path: str,
        seed_file_path: str,
        target_structure: Structure | None = None,
    ) -> list[QueryExecResult]:
        if target_structure is None:
            raise ValueError("target_structure is required for this strategy")

        self._assert_table_exists(connector=connector, table_path=table_path)

        rows = self._load_rows(seed_file_path)
        self._validate_columns(rows=rows, target_structure=target_structure)
        pk_columns = self._get_primary_key_columns(target_structure)

        column_list, tuple_rows = self._rows_to_tuples(rows)
        return connector.bulk_insert_into(
            table_path=table_path,
            rows=tuple_rows,
            column_list=column_list,
            conflict_merge_fields=pk_columns,
        )


_BIGQUERY_STRATEGY_MAP: dict[str, SeedWriteStrategy] = {
    FlowUpdateStrategies.OVERWRITE: BigQuerySeedOverwriteStrategy(),
    FlowUpdateStrategies.INSERT: BigQuerySeedInsertStrategy(),
    FlowUpdateStrategies.UPSERT: BigQuerySeedUpsertStrategy(),
}


def get_seed_strategy(strategy_name: str) -> SeedWriteStrategy:
    """Get the BigQuery seed strategy instance for the given name."""
    strategy = _BIGQUERY_STRATEGY_MAP.get(strategy_name)
    if strategy is None:
        raise ValueError(f"Unknown BigQuery seed strategy: '{strategy_name}'")
    return strategy
