from typing import Any, Self

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

from nld.connector.base import ConnectionState, ConnectionWrapper
from nld.connector.base.events import ConnectionOpened
from snowflake.connector import SnowflakeConnection
from snowflake.connector import connect as snowflake_connect

from .snowflake_credential import (
    SnowflakeAuthenticator,
    SnowflakeCredential,
)


class SnowflakeConnectionWrapper(
    ConnectionWrapper[SnowflakeCredential, SnowflakeConnection]
):
    def __init__(
        self,
        name: str,
        credentials: SnowflakeCredential,
        state: ConnectionState = ConnectionState.INIT,
        connection: SnowflakeConnection | None = None,
    ) -> None:
        super().__init__(
            name=name,
            credentials=credentials,
            state=state,
            connection=connection,
        )

    @property
    def type(self) -> str:
        return "snowflake"

    def _get_active_catalog(self) -> str | None:
        return self.credentials.database_name

    def get_active_schema(self) -> str | None:
        return self.credentials.schema_name

    @staticmethod
    def _load_private_key(
        private_key_path: str, passphrase: str | None = None
    ) -> bytes:
        with open(private_key_path, "rb") as key_file:
            private_key = serialization.load_pem_private_key(
                key_file.read(),
                password=passphrase.encode() if passphrase else None,
                backend=default_backend(),
            )
        key_bytes: bytes = private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return key_bytes

    def open(self) -> Self:
        if self.is_opened():
            self.log_info(f"Connection {self.name} is already opened.")
            return self
        if self.credentials is not None:
            self.log_info("Snowflake Connection opening")
            self.log_debug(f"Account : {self.credentials.account}")
            self.log_debug(f"User : {self.credentials.user}")
            self.log_debug(f"Authenticator : {self.credentials.authenticator}")

            connect_params: dict[str, Any] = {
                "account": self.credentials.account,
                "user": self.credentials.user,
                "authenticator": self.credentials.authenticator,
            }

            if self.credentials.database_name:
                connect_params["database"] = self.credentials.database_name
            if self.credentials.schema_name:
                connect_params["schema"] = self.credentials.schema_name
            if self.credentials.role:
                connect_params["role"] = self.credentials.role
            if self.credentials.warehouse:
                connect_params["warehouse"] = self.credentials.warehouse

            if self.credentials.authenticator == SnowflakeAuthenticator.SNOWFLAKE.value:
                self.log_info("Using username/password authentication")
                connect_params["password"] = self.credentials.password

            elif (
                self.credentials.authenticator
                == SnowflakeAuthenticator.SNOWFLAKE_JWT.value
            ):
                self.log_info("Using key pair authentication (JWT)")
                if self.credentials.private_key_path is None:
                    raise ValueError("private_key_path is required for JWT auth")
                private_key = self._load_private_key(
                    self.credentials.private_key_path,
                    self.credentials.private_key_passphrase,
                )
                connect_params["private_key"] = private_key

            else:
                raise ValueError(
                    f"Unsupported authenticator: {self.credentials.authenticator}"
                )

            self.connection = snowflake_connect(**connect_params)
            self.state = ConnectionState.OPEN
            self.log_event(ConnectionOpened(connection_name=self.name))
        return self
