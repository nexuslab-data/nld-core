from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any

from nld.connector.sqlite.constants import SQLITE_SCHEMA

if TYPE_CHECKING:
    from nld.connector.sqlite.engine.sqlite_native.connector import (
        SQLiteSQLConnector,
    )


class SQLiteBackendMixin(abc.ABC):
    """Mixin providing common SQLite backend functionality.

    This mixin contains shared properties for SQLite-based state backend
    managers, avoiding code duplication between execution and incremental
    backends.

    Requires the implementing class to have:
        - backend_connector: SQLiteSQLConnector
        - parameters: dict[str, Any]
    """

    backend_connector: SQLiteSQLConnector
    parameters: dict[str, Any]

    @property
    def backend_schema_name(self) -> str:
        """Resolve the schema name, always ``main`` on SQLite.

        A declared schema is kept when a project sets one, so the backend
        tables are addressed the way the project spells them; the connector
        collapses the path onto the single namespace either way.
        """
        if "schema_name" in self.parameters:
            return self.parameters["schema_name"]  # type: ignore[no-any-return]

        active_schema = self.backend_connector.get_active_schema()
        if active_schema:
            return active_schema

        return SQLITE_SCHEMA
