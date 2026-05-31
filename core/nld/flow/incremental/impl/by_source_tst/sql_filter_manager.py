from typing import cast

import sqlglot
from sqlglot import exp

from nld.flow.definition.flow_definition import (
    DataFlowStructurePredecessor,
    resolve_master_predecessors,
)
from nld.flow.incremental.base.sql_filter_manager import IncrementalSqlFilterManager
from nld.flow.incremental.impl.by_source_tst.state import BySourceTstProcessingState
from nld.utils.sqlglot.base_dml import BaseSqlglotDMLBuilder
from nld.utils.sqlglot.utils import find_table_reference, get_table_alias_or_name


class BySourceTstSqlFilterManager(IncrementalSqlFilterManager):
    """Timestamp-based incremental SQL filter.

    Injects WHERE clauses filtering on the REC_LAST_UPDATE_TST field
    of each MASTER predecessor table using the processing state
    timestamps.
    """

    def __init__(
        self,
        processing_state: BySourceTstProcessingState,
    ) -> None:
        self.processing_state = processing_state

    def apply_filter(
        self,
        sql_query: str,
        predecessors: dict[str, DataFlowStructurePredecessor],
        dialect: str,
    ) -> str:
        """Apply timestamp-based incremental filtering to a SQL query."""
        masters = resolve_master_predecessors(predecessors)
        if not masters:
            return sql_query

        parsed = sqlglot.parse_one(
            sql_query,
            dialect=dialect,
        )

        for _, master_predecessor in masters:
            master_structure = master_predecessor.full_path.resolve(
                entity_type="structure",
            )

            tst_field = master_structure.get_last_update_tst_field()
            if tst_field is None:
                raise ValueError(
                    f"Structure '{master_structure.name}' has no "
                    f"REC_LAST_UPDATE_TST field required for "
                    f"by_source_tst incremental filtering."
                )

            table_node = find_table_reference(
                parsed,
                table_name=master_structure.name,
            )
            if table_node is None:
                raise ValueError(
                    f"Master predecessor table '{master_structure.name}' "
                    f"not found in the SQL query."
                )

            table_qualifier = get_table_alias_or_name(table_node)
            dml_builder = BaseSqlglotDMLBuilder(dialect=dialect)
            condition = dml_builder.build_timestamp_condition(
                table_qualifier=table_qualifier,
                field_name=tst_field.name,
                start_timestamp=self.processing_state.pull_from_timestamp,
                end_timestamp=self.processing_state.pull_to_timestamp,
            )
            if condition is not None:
                select = cast(exp.Select, parsed)
                parsed = select.where(condition)

        return str(parsed.sql(dialect=dialect))
