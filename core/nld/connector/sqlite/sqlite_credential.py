from nld.connector.base import BaseSqlCredential


class SQLiteCredential(BaseSqlCredential):
    """Credential class for SQLite connections.

    SQLite is a single file with a single namespace, so the only required
    parameter is the database file path (or ``:memory:``). ``schema_name``
    is fixed to ``main``: it exists to satisfy the generic SQL connector
    contract, not to select anything.
    """

    database_name: str
    schema_name: str | None = "main"
    busy_timeout_ms: int = 5000

    @property
    def type(self) -> str:
        return "sqlite"
