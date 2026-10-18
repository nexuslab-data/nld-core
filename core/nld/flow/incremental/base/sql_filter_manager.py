import abc

from nld.flow.definition.flow_definition import DataFlowStructurePredecessor


class IncrementalSqlFilterManager(abc.ABC):
    """Abstract base for incremental SQL query filtering.

    Each incremental type provides its own implementation
    that injects the appropriate WHERE clauses into SQL queries.
    """

    @abc.abstractmethod
    def apply_filter(
        self,
        sql_query: str,
        predecessors: dict[str, DataFlowStructurePredecessor],
        dialect: str,
        input_database_names: dict[str, str] | None = None,
    ) -> str:
        """Apply incremental WHERE clause filtering to the SQL query.

        ``input_database_names`` maps a predecessor key to the database
        its namespace is declared in. A read of the input qualified with
        another database, e.g. ``OTHER_DB.RAW.ORDERS``, is not the input.
        """
        raise NotImplementedError("'apply_filter' method is not yet implemented")
