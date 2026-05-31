import duckdb
from nld.connector.base import ConnectionState, ConnectionWrapper
from nld.connector.base.events import ConnectionOpened
from nld.connector.duckdb.duckdb_credential import DuckDBCredential
from nld.utils.sqlglot import quote_identifier


class DuckDBConnectionWrapper(
    ConnectionWrapper[DuckDBCredential, duckdb.DuckDBPyConnection]
):
    """A wrapper for a DuckDB connection.

    This class manages the lifecycle of a DuckDB connection, including
    opening and closing the connection.
    """

    def __init__(
        self,
        name: str,
        credentials: DuckDBCredential,
        state: ConnectionState = ConnectionState.INIT,
        connection: duckdb.DuckDBPyConnection | None = None,
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
        return "duckdb"

    def get_active_database(self) -> str | None:
        """Return the active catalog (database) for the connection.

        Queries DuckDB's ``current_catalog()`` each time to stay
        correct after ``USE`` statements that change the active
        catalog.  The query is in-process (no network) so the
        overhead is negligible.
        """
        if self.connection is not None and self.is_opened():
            result = self.connection.execute("SELECT current_catalog()").fetchone()
            if result:
                return result[0]  # type: ignore[no-any-return]
        return self.credentials.database_name

    def get_active_schema(self) -> str | None:
        """Return the active schema for the connection.

        Queries DuckDB's ``current_schema()`` each time to stay
        correct after ``USE`` or ``SET schema`` statements.
        """
        if self.connection is not None and self.is_opened():
            result = self.connection.execute("SELECT current_schema()").fetchone()
            if result:
                return result[0]  # type: ignore[no-any-return]
        return self.credentials.schema_name

    def open(self) -> "DuckDBConnectionWrapper":
        """Open the DuckDB connection.

        Returns:
            The current instance of the connection wrapper.
        """
        if self.is_opened():
            self.log_info(f"Connection {self.name} is already opened.")
            return self
        if self.credentials is not None:
            self._open_duckdb_connection()
        return self

    def _open_duckdb_connection(self) -> None:
        """Open the DuckDB connection using the provided credentials."""
        self.log_debug("DuckDB Connection to be opened.")
        self.log_debug(f"Database: {self.credentials.database_name}")
        self.log_debug(f"Schema: {self.credentials.schema_name}")

        self.connection = duckdb.connect(
            database=self.credentials.database_name,
        )

        # Set the active schema if configured (DuckDB defaults to 'main')
        if self.credentials.schema_name and self.credentials.schema_name != "main":
            safe_schema_id = quote_identifier(
                self.credentials.schema_name, dialect="duckdb"
            )
            safe_schema_lit = self.credentials.schema_name.replace("'", "''")
            self.connection.execute(f"CREATE SCHEMA IF NOT EXISTS {safe_schema_id}")
            self.connection.execute(f"SET schema='{safe_schema_lit}'")

        self.state = ConnectionState.OPEN
        self.log_event(ConnectionOpened(connection_name=self.name))
