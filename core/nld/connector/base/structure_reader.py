from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from nld.structure import Structure

from .connector import DataConnector, SQLDataConnector


class ConnectorStructureReader[CONNECTOR: DataConnector[Any]](ABC):
    """Abstract base class for extracting database structure metadata.

    This class defines the interface for extracting structure information
    (tables, views, columns, constraints) from various database connectors.
    """

    def __init__(self, connector: CONNECTOR) -> None:
        self._connector = connector

    @abstractmethod
    def extract_structures(self, **kwargs: Any) -> list[Structure]:
        """Extract structures from the data source.

        Returns:
            List of Structure objects.
        """
        ...


class SQLConnectorStructureReader[CONNECTOR: SQLDataConnector[Any]](
    ConnectorStructureReader[CONNECTOR],
):
    """Structure reader for SQL-based connectors.

    Adds SQL-specific capabilities such as active database awareness
    and filtering by database, schema, and object name.

    Subclasses must implement:
        - active_database: Property returning the current database name.
        - extract_structures: Method to extract structure metadata.
    """

    @property
    @abstractmethod
    def active_database(self) -> str | None:
        """Get the active database name from the connection.

        Returns:
            The database name, or None if not applicable.
        """
        ...

    @abstractmethod
    def extract_structures(
        self,
        database: str | None = None,
        schema: str | None = None,
        object_name: str | None = None,
        **kwargs: Any,
    ) -> list[Structure]:
        """Extract structures (tables/views) from the database.

        Args:
            database: Optional database name. When None, falls back
                to active_database.
            schema: Optional schema name to filter by.
            object_name: Optional table/view name to filter by.

        Returns:
            List of Structure objects representing tables and views.
        """
        ...
