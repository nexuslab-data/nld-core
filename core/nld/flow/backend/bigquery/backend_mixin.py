import abc
from typing import Any

from nld.connector.bigquery.bigquery_connector import BigQueryConnector


class BigQueryBackendMixin(abc.ABC):
    """
    Mixin providing common BigQuery backend functionality.

    Requires the implementing class to have:
        - backend_connector: BigQueryConnector
        - parameters: dict[str, Any]
    """

    backend_connector: BigQueryConnector
    parameters: dict[str, Any]

    @property
    def backend_schema_name(self) -> str:
        """Resolve the dataset name from parameters or connector.

        BigQuery datasets play the role of schemas in the connector
        abstraction shared with other SQL backends.
        """
        if "schema_name" in self.parameters:
            return self.parameters["schema_name"]  # type: ignore[no-any-return]

        active_schema = self.backend_connector.get_active_schema()
        if active_schema:
            return active_schema

        raise ValueError(
            "BigQuery backend requires a dataset: set ``schema_name`` "
            "in parameters or configure ``schema_name`` "
            "(or ``dataset_id``) on the BigQuery credentials."
        )
