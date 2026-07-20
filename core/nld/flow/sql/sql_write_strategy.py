import abc
from typing import Any

from nld.connector.base.connector import SQLDataConnector
from nld.connector.base.query import QueryExecResult
from nld.flow.utils.flow_update_strategy import FlowUpdateStrategies
from nld.structure import Structure
from nld.structure.field.field_characterisation_definition import (
    FieldCharacterisationDefinitionNames,
)


class SQLWriteStrategy(abc.ABC):
    """Abstract base class for SQL write strategies.

    Each strategy defines how data is written to the target table
    during SQL flow execution.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """The strategy name matching the FlowUpdateStrategies value."""

    @property
    @abc.abstractmethod
    def requires_target_structure(self) -> bool:
        """Whether this strategy requires a resolved target structure."""

    @property
    def requires_primary_key(self) -> bool:
        """Whether this strategy requires primary key fields on the structure."""
        return False

    @property
    def structure_type(self) -> str:
        """The database object type produced by this strategy."""
        return "TABLE"

    @abc.abstractmethod
    def execute(
        self,
        connector: SQLDataConnector[Any],
        table_path: str,
        sql_query: str,
        target_structure: Structure | None = None,
    ) -> list[QueryExecResult]:
        """Execute the write strategy and return a list of query execution results.

        Args:
            connector: the SQL connector to use for execution.
            table_path: fully qualified target table path.
            sql_query: the SELECT query providing the data.
            target_structure: resolved target structure with column
                and primary key information (required for some strategies).

        Returns:
            A list of QueryExecResult for each query executed. On failure,
            the list is returned early with the failed result as the
            last element.

        Raises:
            ValueError: if required parameters are missing.
        """

    def _get_column_list(self, target_structure: Structure | None) -> list[str]:
        """Extract column names from the target structure."""
        if target_structure is None:
            raise ValueError("target_structure is required for this strategy")
        return [field.name for field in target_structure.get_all_fields()]

    def _get_primary_key_columns(
        self,
        target_structure: Structure | None,
    ) -> list[str]:
        """Extract primary key column names from the target structure."""
        if target_structure is None:
            raise ValueError("target_structure is required for this strategy")
        if not target_structure.has_primary_key():
            raise ValueError(
                "target_structure must have a primary key defined for this strategy"
            )
        return [field.name for field in target_structure.get_primary_key_fields()]

    def _get_upsert_field_params(
        self,
        target_structure: Structure | None,
    ) -> tuple[list[str] | None, dict[str, str] | None, list[str] | None]:
        """Resolve UPSERT field parameters from the target structure.

        Returns exclude_from_update, expression_overrides, and
        exclude_from_match based on field characterisations.

        The insert timestamp field (REC_INSERT_TST) is excluded from
        the UPDATE SET clause. The last update timestamp field
        (REC_LAST_UPDATE_TST) is overridden with CURRENT_TIMESTAMP.
        Fields with EXCLUDE_FROM_UPSERT_UPDATE are excluded from
        both UPDATE SET and change detection. Fields with
        EXCLUDE_FROM_UPSERT_MATCH are updated but excluded from
        change detection.
        """
        if target_structure is None:
            return None, None, None

        exclude_from_update: list[str] = []
        expression_overrides: dict[str, str] = {}
        exclude_from_match: list[str] = []

        insert_tst_field = target_structure.get_field_name_with_characterisation(
            FieldCharacterisationDefinitionNames.REC_INSERT_TST,
        )
        if insert_tst_field is not None:
            exclude_from_update.append(insert_tst_field)

        update_tst_field = target_structure.get_field_name_with_characterisation(
            FieldCharacterisationDefinitionNames.REC_LAST_UPDATE_TST,
        )
        if update_tst_field is not None:
            expression_overrides[update_tst_field] = "CURRENT_TIMESTAMP"

        for field_name in target_structure.get_field_names_with_characterisation(
            FieldCharacterisationDefinitionNames.EXCLUDE_FROM_UPSERT_UPDATE,
        ):
            if field_name not in exclude_from_update:
                exclude_from_update.append(field_name)

        for field_name in target_structure.get_field_names_with_characterisation(
            FieldCharacterisationDefinitionNames.EXCLUDE_FROM_UPSERT_MATCH,
        ):
            exclude_from_match.append(field_name)

        return (
            exclude_from_update or None,
            expression_overrides or None,
            exclude_from_match or None,
        )


class OverwriteStrategy(SQLWriteStrategy):
    """TRUNCATE TABLE + INSERT INTO ... SELECT.

    This is the default strategy. The target table is truncated
    and reloaded from the query result on every run. The table
    must already exist (managed by structure deploy).
    """

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
        sql_query: str,
        target_structure: Structure | None = None,
    ) -> list[QueryExecResult]:
        results: list[QueryExecResult] = []

        truncate_result = connector.truncate_table(
            table_path=table_path,
        )
        results.append(truncate_result)
        if truncate_result.failed():
            return results

        column_list = self._get_column_list(target_structure)
        insert_result = connector.insert_into_from_query(
            table_path=table_path,
            sql_query=sql_query,
            column_list=column_list,
        )
        results.append(insert_result)
        return results


class ViewStrategy(SQLWriteStrategy):
    """CREATE OR REPLACE VIEW AS.

    Creates a database view instead of a materialized table.
    The view is always up-to-date since it executes the query
    at read time.
    """

    @property
    def name(self) -> str:
        return FlowUpdateStrategies.VIEW

    @property
    def requires_target_structure(self) -> bool:
        return False

    @property
    def structure_type(self) -> str:
        return "VIEW"

    def execute(
        self,
        connector: SQLDataConnector[Any],
        table_path: str,
        sql_query: str,
        target_structure: Structure | None = None,
    ) -> list[QueryExecResult]:
        results: list[QueryExecResult] = []

        result = connector.create_or_replace_view(
            view_path=table_path,
            sql_query=sql_query,
        )
        results.append(result)
        return results


class InsertStrategy(SQLWriteStrategy):
    """INSERT INTO ... SELECT (append only).

    Appends rows from the query result to the target table
    without checking for duplicates. The target table must
    already exist with a matching structure.
    """

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
        sql_query: str,
        target_structure: Structure | None = None,
    ) -> list[QueryExecResult]:
        results: list[QueryExecResult] = []

        column_list = self._get_column_list(target_structure)
        result = connector.insert_into_from_query(
            table_path=table_path,
            sql_query=sql_query,
            column_list=column_list,
        )
        results.append(result)
        return results


class UpsertStrategy(SQLWriteStrategy):
    """INSERT ... ON CONFLICT DO UPDATE from SELECT.

    Inserts new rows and updates existing ones when a conflict
    on the primary key is detected. Requires a target structure
    with a primary key defined.

    When the target structure has fields characterised as
    REC_INSERT_TST or REC_LAST_UPDATE_TST, timestamp handling
    is applied automatically: the insert timestamp is excluded
    from the UPDATE SET clause, and the last update timestamp
    is overridden with CURRENT_TIMESTAMP.
    """

    @property
    def name(self) -> str:
        return FlowUpdateStrategies.UPSERT

    @property
    def requires_target_structure(self) -> bool:
        return True

    @property
    def requires_primary_key(self) -> bool:
        return True

    def execute(
        self,
        connector: SQLDataConnector[Any],
        table_path: str,
        sql_query: str,
        target_structure: Structure | None = None,
    ) -> list[QueryExecResult]:
        results: list[QueryExecResult] = []

        column_list = self._get_column_list(target_structure)
        pk_columns = self._get_primary_key_columns(target_structure)
        exclude_from_update, expression_overrides, exclude_from_match = (
            self._get_upsert_field_params(target_structure)
        )
        result = connector.upsert_from_query(
            table_path=table_path,
            sql_query=sql_query,
            column_list=column_list,
            upsert_fields=pk_columns,
            exclude_from_update=exclude_from_update,
            expression_overrides=expression_overrides,
            exclude_from_match=exclude_from_match,
        )
        results.append(result)
        return results


class DeleteInsertStrategy(SQLWriteStrategy):
    """DELETE matching keys + INSERT.

    Deletes rows from the target table whose primary key values
    match the query result, then inserts all rows from the query.
    This ensures a clean replacement of the matched subset.
    """

    @property
    def name(self) -> str:
        return FlowUpdateStrategies.DEL_INS

    @property
    def requires_target_structure(self) -> bool:
        return True

    @property
    def requires_primary_key(self) -> bool:
        return True

    def execute(
        self,
        connector: SQLDataConnector[Any],
        table_path: str,
        sql_query: str,
        target_structure: Structure | None = None,
    ) -> list[QueryExecResult]:
        results: list[QueryExecResult] = []

        column_list = self._get_column_list(target_structure)
        pk_columns = self._get_primary_key_columns(target_structure)

        delete_result = connector.delete_from_query(
            table_path=table_path,
            sql_query=sql_query,
            key_columns=pk_columns,
        )
        results.append(delete_result)
        if delete_result.failed():
            return results

        insert_result = connector.insert_into_from_query(
            table_path=table_path,
            sql_query=sql_query,
            column_list=column_list,
        )
        results.append(insert_result)
        return results


class UpsertLogicalDeleteStrategy(SQLWriteStrategy):
    """UPSERT + mark absent rows as logically deleted.

    Performs an upsert (INSERT ... ON CONFLICT DO UPDATE) from
    the query result, then marks rows that are present in the
    target table but absent from the query result as logically
    deleted by setting the deletion flag column to True.

    The deletion flag column is resolved dynamically from the
    target structure using the REC_DELETION_FLAG characterisation.
    """

    @property
    def name(self) -> str:
        return FlowUpdateStrategies.UPSERT_LOG_DEL

    @property
    def requires_target_structure(self) -> bool:
        return True

    @property
    def requires_primary_key(self) -> bool:
        return True

    def execute(
        self,
        connector: SQLDataConnector[Any],
        table_path: str,
        sql_query: str,
        target_structure: Structure | None = None,
    ) -> list[QueryExecResult]:
        results: list[QueryExecResult] = []

        column_list = self._get_column_list(target_structure)
        pk_columns = self._get_primary_key_columns(target_structure)
        deletion_flag_column = self._get_deletion_flag_column(target_structure)
        exclude_from_update, expression_overrides, exclude_from_match = (
            self._get_upsert_field_params(target_structure)
        )

        upsert_result = connector.upsert_from_query(
            table_path=table_path,
            sql_query=sql_query,
            column_list=column_list,
            upsert_fields=pk_columns,
            exclude_from_update=exclude_from_update,
            expression_overrides=expression_overrides,
            exclude_from_match=exclude_from_match,
        )
        results.append(upsert_result)
        if upsert_result.failed():
            return results

        mark_result = connector.mark_absent_rows_deleted(
            table_path=table_path,
            sql_query=sql_query,
            key_columns=pk_columns,
            deletion_flag_column=deletion_flag_column,
        )
        results.append(mark_result)
        return results

    def _get_deletion_flag_column(
        self,
        target_structure: Structure | None,
    ) -> str:
        """Resolve the deletion flag column from the target structure."""
        if target_structure is None:
            raise ValueError("target_structure is required for this strategy")
        deletion_flag_column = target_structure.get_field_name_with_characterisation(
            FieldCharacterisationDefinitionNames.REC_DELETION_FLAG,
        )
        if deletion_flag_column is None:
            raise ValueError(
                f"target_structure must have exactly one field with "
                f"'{FieldCharacterisationDefinitionNames.REC_DELETION_FLAG}' "
                f"characterisation"
            )
        return deletion_flag_column


_STRATEGY_MAP: dict[str, SQLWriteStrategy] = {
    FlowUpdateStrategies.OVERWRITE: OverwriteStrategy(),
    FlowUpdateStrategies.VIEW: ViewStrategy(),
    FlowUpdateStrategies.INSERT: InsertStrategy(),
    FlowUpdateStrategies.UPSERT: UpsertStrategy(),
    FlowUpdateStrategies.DEL_INS: DeleteInsertStrategy(),
    FlowUpdateStrategies.UPSERT_LOG_DEL: UpsertLogicalDeleteStrategy(),
}


def get_write_strategy(strategy_name: str) -> SQLWriteStrategy:
    """Get the write strategy instance for the given strategy name.

    Args:
        strategy_name: the strategy name matching a FlowUpdateStrategies value.

    Returns:
        The corresponding SQLWriteStrategy instance.

    Raises:
        ValueError: if the strategy name is not recognized.
    """
    strategy = _STRATEGY_MAP.get(strategy_name.upper())
    if strategy is None:
        raise ValueError(
            f"Unknown write strategy: '{strategy_name}'. "
            f"Valid strategies: {list(_STRATEGY_MAP.keys())}"
        )
    return strategy
