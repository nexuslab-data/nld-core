import abc

from nld.flow.definition.flow_definition import DataFlowStructurePredecessor


class IncrementalSqlFilterManager(abc.ABC):
    """Abstract base for incremental SQL query filtering.

    Each incremental strategy provides its own implementation
    that injects the appropriate WHERE clauses into SQL queries.
    """

    @abc.abstractmethod
    def apply_filter(
        self,
        sql_query: str,
        predecessors: dict[str, DataFlowStructurePredecessor],
        dialect: str,
    ) -> str:
        """Apply incremental WHERE clause filtering to the SQL query."""
        raise NotImplementedError("'apply_filter' method is not yet implemented")
