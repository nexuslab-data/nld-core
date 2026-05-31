from nld.connector.base import ConnectorPlugin

from .bigquery_connection import BigQueryConnectionWrapper
from .bigquery_connector import BigQueryConnector
from .bigquery_credential import BigQueryCredential
from .bigquery_data_type import BigQueryDataTypes
from .bigquery_structure import BigQueryStructure
from .query_wrapper import BigQueryQueryWrapper
from .service import (
    BigQueryStructureDiffDDLGenerator,
    BigQueryStructureReader,
)

Plugin = ConnectorPlugin(
    connector_class=BigQueryConnector,
    connection_wrapper_class=BigQueryConnectionWrapper,
    credentials_class=BigQueryCredential,
    structure_class_path="nld.connector.bigquery.bigquery_structure.BigQueryStructure",
)

__all__ = [
    "BigQueryConnectionWrapper",
    "BigQueryConnector",
    "BigQueryCredential",
    "BigQueryDataTypes",
    "BigQueryQueryWrapper",
    "BigQueryStructure",
    "BigQueryStructureDiffDDLGenerator",
    "BigQueryStructureReader",
]
