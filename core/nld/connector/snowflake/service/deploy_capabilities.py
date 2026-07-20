from nld.connector.base import (
    ConnectorDeployCapabilities,
    resolve_sqlglot_dialect,
)
from nld.connector.snowflake.connector_definition import (
    SNOWFLAKE_CONNECTOR_DEFINITION,
)
from nld.structure.structure.structure_characterisation_def import (
    StructureCharacterisationDefinitionNames,
)

SNOWFLAKE_DEPLOY_CAPABILITIES = ConnectorDeployCapabilities(
    dialect=resolve_sqlglot_dialect("snowflake"),
    # Snowflake only allows SET DEFAULT on sequence-backed columns;
    # a scalar default change falls back to REBUILD.
    alter_column_set_default=False,
    add_column_positioned=False,
    comparable_characterisations=[
        StructureCharacterisationDefinitionNames.PRIMARY_KEY,
        StructureCharacterisationDefinitionNames.UNIQUE,
    ],
    comparable_data_type_aliases=(
        SNOWFLAKE_CONNECTOR_DEFINITION.comparable_data_type_aliases
    ),
    enforce_field_order_default=True,
    rename_column_in_place=True,
    rename_table_in_place=True,
)
