import os
import sqlite3

from nld.connector.base import ConnectionState, ConnectionWrapper
from nld.connector.base.events import ConnectionOpened
from nld.connector.sqlite.constants import SQLITE_SCHEMA
from nld.connector.sqlite.sqlite_credential import SQLiteCredential

IN_MEMORY_DATABASE_NAME = ":memory:"


class SQLiteConnectionWrapper(ConnectionWrapper[SQLiteCredential, sqlite3.Connection]):
    """A wrapper for a SQLite connection.

    Opens the connection in autocommit mode (``isolation_level=None``) so the
    connector owns transaction boundaries explicitly through BEGIN, COMMIT and
    ROLLBACK statements, the same way the DuckDB connector does. The Python
    driver would otherwise open implicit transactions around DML only, leaving
    DDL outside them.
    """

    def __init__(
        self,
        name: str,
        credentials: SQLiteCredential,
        state: ConnectionState = ConnectionState.INIT,
        connection: sqlite3.Connection | None = None,
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
        return "sqlite"

    def get_active_database(self) -> str | None:
        """Return the database file backing the connection."""
        return self.credentials.database_name

    def get_active_schema(self) -> str | None:
        """Return the active schema, always ``main`` on SQLite."""
        return SQLITE_SCHEMA

    def open(self) -> "SQLiteConnectionWrapper":
        """Open the SQLite connection.

        Returns:
            The current instance of the connection wrapper.
        """
        if self.is_opened():
            self.log_info(f"Connection {self.name} is already opened.")
            return self
        if self.credentials is not None:
            self._open_sqlite_connection()
        return self

    def _open_sqlite_connection(self) -> None:
        """Open the SQLite connection using the provided credentials."""
        database_name = self.credentials.database_name
        self.log_debug("SQLite Connection to be opened.")
        self.log_debug(f"Database: {database_name}")

        if database_name != IN_MEMORY_DATABASE_NAME:
            parent_directory = os.path.dirname(os.path.abspath(database_name))
            os.makedirs(parent_directory, exist_ok=True)

        self.connection = sqlite3.connect(
            database=database_name,
            isolation_level=None,
        )
        self._apply_pragmas()

        self.state = ConnectionState.OPEN
        self.log_event(ConnectionOpened(connection_name=self.name))

    def _apply_pragmas(self) -> None:
        """Apply the connection pragmas the framework relies on.

        WAL keeps a reader from blocking the writer, which a single-process
        application server needs as soon as it serves two requests at once;
        foreign keys are off by default in SQLite and would silently ignore
        every declared reference; the busy timeout turns a concurrent write
        into a wait instead of an immediate "database is locked".
        """
        if self.connection is None:
            return
        if self.credentials.database_name != IN_MEMORY_DATABASE_NAME:
            self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute(
            f"PRAGMA busy_timeout={int(self.credentials.busy_timeout_ms)}"
        )
