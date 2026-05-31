from typing import Any

import psycopg2
from nld.connector.base import ConnectionState, ConnectionWrapper
from nld.connector.base.events import ConnectionOpened
from nld.connector.postgresql.postgresql_credential import (
    PostgreSQLCredential,
)
from psycopg2.extensions import connection as Psycopg2Connection


class Psycopg2SQLConnectionWrapper(
    ConnectionWrapper[PostgreSQLCredential, Psycopg2Connection]
):
    """A wrapper for a PostgreSQL connection.

    This class manages the lifecycle of a PostgreSQL connection, including
    opening and closing the connection, and provides methods for interacting
    with the database.
    """

    def __init__(
        self,
        name: str,
        credentials: PostgreSQLCredential,
        state: ConnectionState = ConnectionState.INIT,
        connection: Psycopg2Connection | None = None,
    ) -> None:
        super().__init__(
            name=name,
            credentials=credentials,
            state=state,
            connection=connection,
        )

    @property
    def type(self) -> str:
        """Return the type of the connection."""
        return "postgresql"

    def get_active_database(self) -> str | None:
        """Return the active catalog (database) for the connection."""
        return self.credentials.database_name

    def get_active_schema(self) -> str | None:
        """Return the active schema for the connection."""
        return self.credentials.schema_name

    def open(self) -> "Psycopg2SQLConnectionWrapper":
        """Open the PostgreSQL connection.

        If the connection is already opened, it does nothing. If the connection
        is not opened, it attempts to open it using the provided credentials.

        Returns:
            The current instance of the connection wrapper.
        """
        if self.is_opened():
            self.log_info(f"Connection {self.name} is already opened.")
            return self
        if self.credentials is not None:
            self._open_postgresql_connection()
        return self

    def _open_postgresql_connection(self) -> None:
        """Open the PostgreSQL connection using the provided credentials."""
        self.log_debug("PostgreSQL Connection to be opened.")
        self.log_debug(f"Host: {self.credentials.host}")
        self.log_debug(f"Port: {self.credentials.port}")
        self.log_debug(f"Database: {self.credentials.database_name}")
        self.log_debug(f"User: {self.credentials.user}")
        self.log_debug("Password: ***")
        self.log_debug(f"SSL mode: {self.credentials.sslmode}")

        connect_params: dict[str, Any] = {
            "host": self.credentials.host,
            "port": self.credentials.port,
            "database": self.credentials.database_name,
            "user": self.credentials.user,
            "password": self.credentials.password,
        }
        if self.credentials.sslmode:
            connect_params["sslmode"] = self.credentials.sslmode
        if self.credentials.sslrootcert:
            connect_params["sslrootcert"] = self.credentials.sslrootcert

        self.connection = psycopg2.connect(**connect_params)
        self.state = ConnectionState.OPEN
        self.log_event(ConnectionOpened(connection_name=self.name))
