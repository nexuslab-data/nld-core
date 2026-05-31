import abc
from typing import Any

from nld.connector.postgresql.engine.psycopg2.connector import Psycopg2SQLConnector


class PostgreSQLBackendMixin(abc.ABC):
    """
    Mixin providing common PostgreSQL backend functionality.

    This mixin contains shared properties for PostgreSQL-based state
    backend managers, avoiding code duplication between execution and
    incremental backends.

    Requires the implementing class to have:
        - backend_connector: Psycopg2SQLConnector
        - parameters: dict[str, Any]
    """

    backend_connector: Psycopg2SQLConnector
    parameters: dict[str, Any]

    @property
    def backend_schema_name(self) -> str:
        """Resolve the schema name from parameters or connector."""
        if "schema_name" in self.parameters:
            return self.parameters["schema_name"]  # type: ignore[no-any-return]

        active_schema = self.backend_connector.get_active_schema()
        if active_schema:
            return active_schema

        return "public"
