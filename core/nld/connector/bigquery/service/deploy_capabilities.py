from nld.connector.base import (
    ConnectorDeployCapabilities,
    resolve_sqlglot_dialect,
)
from nld.connector.bigquery.connector_definition import (
    BIGQUERY_CONNECTOR_DEFINITION,
)
from nld.structure.structure.structure_characterisation_def import (
    StructureCharacterisationDefinitionNames,
)

BIGQUERY_DEPLOY_CAPABILITIES = ConnectorDeployCapabilities(
    dialect=resolve_sqlglot_dialect("bigquery"),
    alter_column_set_default=True,
    add_column_positioned=False,
    comparable_characterisations=[
        StructureCharacterisationDefinitionNames.PRIMARY_KEY,
    ],
    comparable_data_type_aliases=(
        BIGQUERY_CONNECTOR_DEFINITION.comparable_data_type_aliases
    ),
    enforce_field_order_default=False,
    rename_column_in_place=False,
    rename_table_in_place=False,
)
