from nld.connector.base import ConnectorPlugin

from .bigquery_connection import BigQueryConnectionWrapper
from .bigquery_connector import BigQueryConnector
from .bigquery_credential import BigQueryCredential
from .bigquery_structure import BigQueryStructure
from .connector_definition import (
    BIGQUERY_CONNECTOR_DEFINITION,
    BigQueryConnectorDefinition,
    BigQueryDataTypes,
)
from .query_wrapper import BigQueryQueryWrapper
from .service import (
    BIGQUERY_DEPLOY_CAPABILITIES,
    BigQueryStructureDiffDDLStatementBuilder,
    BigQueryStructureReader,
)

Plugin = ConnectorPlugin(
    connector_class=BigQueryConnector,
    connection_wrapper_class=BigQueryConnectionWrapper,
    credentials_class=BigQueryCredential,
    structure_class_path="nld.connector.bigquery.bigquery_structure.BigQueryStructure",
)

__all__ = [
    "BIGQUERY_CONNECTOR_DEFINITION",
    "BIGQUERY_DEPLOY_CAPABILITIES",
    "BigQueryConnectionWrapper",
    "BigQueryConnector",
    "BigQueryConnectorDefinition",
    "BigQueryCredential",
    "BigQueryDataTypes",
    "BigQueryQueryWrapper",
    "BigQueryStructure",
    "BigQueryStructureDiffDDLStatementBuilder",
    "BigQueryStructureReader",
]
