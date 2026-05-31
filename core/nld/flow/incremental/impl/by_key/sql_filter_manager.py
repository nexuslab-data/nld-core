from typing import cast

import sqlglot
from sqlglot import exp

from nld.flow.definition.flow_definition import (
    DataFlowStructurePredecessor,
    resolve_master_predecessors,
)
from nld.flow.incremental.base.sql_filter_manager import IncrementalSqlFilterManager
from nld.flow.incremental.impl.by_key.state import ByKeyProcessingState
from nld.flow.utils import FlowLoadingStrategies
from nld.utils.sqlglot.base_dml import BaseSqlglotDMLBuilder
from nld.utils.sqlglot.utils import find_table_reference, get_table_alias_or_name


class ByKeySqlFilterManager(IncrementalSqlFilterManager):
    """Key-based incremental SQL filter.

    Injects WHERE clauses filtering on the key_field of each
    MASTER predecessor table using the keys to process from the
    processing state.
    """

    def __init__(
        self,
        processing_state: ByKeyProcessingState,
    ) -> None:
        self.processing_state = processing_state

    def apply_filter(
        self,
        sql_query: str,
        predecessors: dict[str, DataFlowStructurePredecessor],
        dialect: str,
    ) -> str:
        """Apply key-based incremental filtering to a SQL query."""
        if self.processing_state.strategy == FlowLoadingStrategies.FULL:
            return sql_query

        keys_to_process = self.processing_state.get_keys_to_process()
        if not keys_to_process:
            return sql_query

        key_names = [key_state.name for key_state in keys_to_process]

        masters = resolve_master_predecessors(predecessors)
        if not masters:
            return sql_query

        parsed = sqlglot.parse_one(
            sql_query,
            dialect=dialect,
        )

        for predecessor_name, master_predecessor in masters:
            if master_predecessor.key_field is None:
                raise ValueError(
                    f"Predecessor '{predecessor_name}' must specify "
                    f"key_field for by_key incremental filtering."
                )

            master_structure = master_predecessor.full_path.resolve(
                entity_type="structure",
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
            condition = dml_builder.build_key_in_condition(
                table_qualifier=table_qualifier,
                field_name=master_predecessor.key_field,
                keys=key_names,
            )
            if condition is not None:
                select = cast(exp.Select, parsed)
                parsed = select.where(condition)

        return str(parsed.sql(dialect=dialect))
