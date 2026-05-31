import abc
from typing import Any

from nld.connector.snowflake.snowflake_connector import SnowflakeConnector


class SnowflakeBackendMixin(abc.ABC):
    """
    Mixin providing common Snowflake backend functionality.

    Requires the implementing class to have:
        - backend_connector: SnowflakeConnector
        - parameters: dict[str, Any]
    """

    backend_connector: SnowflakeConnector
    parameters: dict[str, Any]

    @property
    def backend_schema_name(self) -> str:
        """Resolve the schema name from parameters or connector."""
        if "schema_name" in self.parameters:
            return self.parameters["schema_name"]  # type: ignore[no-any-return]

        active_schema = self.backend_connector.get_active_schema()
        if active_schema:
            return active_schema

        return "PUBLIC"
