from nld.connector.base import BaseSqlCredential


class DuckDBCredential(BaseSqlCredential):
    """Credential class for DuckDB connections.

    Holds the connection parameters required to connect to a DuckDB database.
    DuckDB is file-based, so only a database path and optional schema are needed.
    """

    database_name: str
    schema_name: str | None = "main"

    @property
    def type(self) -> str:
        return "duckdb"
