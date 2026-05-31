from enum import StrEnum

from pydantic import model_validator

from nld.connector.base import BaseSqlCredential


class SnowflakeAuthenticator(StrEnum):
    SNOWFLAKE = "snowflake"
    SNOWFLAKE_JWT = "snowflake_jwt"


class SnowflakeCredential(BaseSqlCredential):
    account: str
    user: str
    authenticator: str
    password: str | None = None
    private_key_path: str | None = None
    private_key_passphrase: str | None = None
    role: str | None = None
    warehouse: str | None = None
    database_name: str | None = None
    schema_name: str | None = None

    @property
    def type(self) -> str:
        return "snowflake"

    @model_validator(mode="after")
    def validate_authenticator_requirements(self) -> "SnowflakeCredential":
        if (
            self.authenticator == SnowflakeAuthenticator.SNOWFLAKE.value
            and not self.password
        ):
            raise ValueError("Password is required for authenticator='snowflake'")
        if (
            self.authenticator == SnowflakeAuthenticator.SNOWFLAKE_JWT.value
            and not self.private_key_path
        ):
            raise ValueError(
                "Private key path is required for authenticator='snowflake_jwt'"
            )
        return self
