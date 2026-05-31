from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nld.connector.duckdb.engine.duckdb_native.connector import (
        DuckDBSQLConnector,
    )


class DuckDBBackendMixin(abc.ABC):
    """Mixin providing common DuckDB backend functionality.

    This mixin contains shared properties for DuckDB-based state
    backend managers, avoiding code duplication between execution and
    incremental backends.

    Requires the implementing class to have:
        - backend_connector: DuckDBSQLConnector
        - parameters: dict[str, Any]
    """

    backend_connector: DuckDBSQLConnector
    parameters: dict[str, Any]

    @property
    def backend_schema_name(self) -> str:
        """Resolve the schema name from parameters or connector."""
        if "schema_name" in self.parameters:
            return self.parameters["schema_name"]  # type: ignore[no-any-return]

        active_schema = self.backend_connector.get_active_schema()
        if active_schema:
            return active_schema

        return "main"
