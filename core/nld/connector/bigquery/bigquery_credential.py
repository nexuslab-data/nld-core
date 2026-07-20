from pydantic import model_validator

from nld.connector.base import BaseSqlCredential


class BigQueryCredential(BaseSqlCredential):
    """Credential class for BigQuery connections.

    Supports three authentication modes:
    - Service account JSON key file via credentials_path.
    - Application Default Credentials (ADC) when credentials_path
      is None.
    - Anonymous against a custom api_endpoint (a BigQuery emulator
      for local development and testing).
    """

    project_id: str
    dataset_id: str | None = None
    schema_name: str | None = None
    location: str | None = None
    credentials_path: str | None = None
    api_endpoint: str | None = None

    @property
    def type(self) -> str:
        return "bigquery"

    @model_validator(mode="after")
    def validate_project_id_not_empty(self) -> "BigQueryCredential":
        if not self.project_id.strip():
            raise ValueError("project_id must not be empty")
        return self
