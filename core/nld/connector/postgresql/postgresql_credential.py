from pydantic import model_validator

from nld.connector.base import BaseSqlCredential

VALID_SSLMODES = ("disable", "allow", "prefer", "require", "verify-ca", "verify-full")


class PostgreSQLCredential(BaseSqlCredential):
    """Credential class for PostgreSQL connections.

    Holds the connection parameters required to connect to a PostgreSQL database.
    """

    host: str
    port: int
    user: str
    password: str
    database_name: str | None = None
    schema_name: str | None = None
    sslmode: str | None = None
    sslrootcert: str | None = None

    @property
    def type(self) -> str:
        return "postgresql"

    @model_validator(mode="after")
    def validate_sslmode(self) -> "PostgreSQLCredential":
        if self.sslmode is not None and self.sslmode not in VALID_SSLMODES:
            raise ValueError(
                f"Invalid sslmode '{self.sslmode}'. "
                f"Must be one of: {', '.join(VALID_SSLMODES)}"
            )
        return self
