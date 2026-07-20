from nld.connector.base import (
    ConnectorDeployCapabilities,
    resolve_sqlglot_dialect,
)
from nld.connector.duckdb.connector_definition import (
    DUCKDB_CONNECTOR_DEFINITION,
)
from nld.structure.structure.structure_characterisation_def import (
    StructureCharacterisationDefinitionNames,
)

DUCKDB_DEPLOY_CAPABILITIES = ConnectorDeployCapabilities(
    dialect=resolve_sqlglot_dialect("duckdb"),
    alter_column_set_default=True,
    add_column_positioned=False,
    comparable_characterisations=[
        StructureCharacterisationDefinitionNames.INDEX,
        StructureCharacterisationDefinitionNames.PRIMARY_KEY,
        StructureCharacterisationDefinitionNames.UNIQUE,
    ],
    comparable_data_type_aliases=(
        DUCKDB_CONNECTOR_DEFINITION.comparable_data_type_aliases
    ),
    enforce_field_order_default=False,
    rename_column_in_place=True,
    rename_table_in_place=True,
)
