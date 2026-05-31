from nld.flow.definition.flow_definition import DataFlowStructurePredecessor
from nld.flow.incremental.base.sql_filter_manager import IncrementalSqlFilterManager


class NoIncrementSqlFilterManager(IncrementalSqlFilterManager):
    """No-op SQL filter for flows without incremental strategy."""

    def apply_filter(
        self,
        sql_query: str,
        predecessors: dict[str, DataFlowStructurePredecessor],
        dialect: str,
    ) -> str:
        """No filtering for no-increment strategy."""
        return sql_query
