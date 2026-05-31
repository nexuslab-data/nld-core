from typing import Self

from google.cloud import bigquery
from google.oauth2 import service_account

from nld.connector.base import ConnectionState, ConnectionWrapper
from nld.connector.base.events import ConnectionOpened
from nld.connector.bigquery.bigquery_credential import BigQueryCredential


class BigQueryConnectionWrapper(ConnectionWrapper[BigQueryCredential, bigquery.Client]):
    """Connection wrapper managing a BigQuery client lifecycle."""

    def __init__(
        self,
        name: str,
        credentials: BigQueryCredential,
        state: ConnectionState = ConnectionState.INIT,
        connection: bigquery.Client | None = None,
    ) -> None:
        super().__init__(
            name=name,
            credentials=credentials,
            state=state,
            connection=connection,
        )

    @property
    def type(self) -> str:
        return "bigquery"

    def get_active_project(self) -> str:
        """Return the GCP project ID from the credentials."""
        return self.credentials.project_id

    def get_active_dataset(self) -> str | None:
        """Return the default dataset ID from the credentials.

        Prefers ``schema_name`` (the canonical cross-connector field) and
        falls back to ``dataset_id`` for BigQuery-specific configs.
        """
        return self.credentials.schema_name or self.credentials.dataset_id

    def open(self) -> Self:
        if self.is_opened():
            self.log_info(f"Connection {self.name} is already opened.")
            return self

        if self.credentials is not None:
            self.log_info("BigQuery connection opening")
            self.log_debug(f"Project: {self.credentials.project_id}")

            if self.credentials.credentials_path is not None:
                self.log_info("Using service account key file authentication")
                gcp_credentials = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call,unused-ignore]
                    self.credentials.credentials_path,
                )
                self.connection = bigquery.Client(
                    project=self.credentials.project_id,
                    credentials=gcp_credentials,
                    location=self.credentials.location,
                )
            else:
                self.log_info("Using Application Default Credentials")
                self.connection = bigquery.Client(
                    project=self.credentials.project_id,
                    location=self.credentials.location,
                )

            self.state = ConnectionState.OPEN
            self.log_event(ConnectionOpened(connection_name=self.name))

        return self
