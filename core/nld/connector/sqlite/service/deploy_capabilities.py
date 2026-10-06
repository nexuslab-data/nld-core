from nld.connector.base import (
    ConnectorDeployCapabilities,
    resolve_sqlglot_dialect,
)
from nld.connector.sqlite.connector_definition import (
    SQLITE_CONNECTOR_DEFINITION,
)
from nld.structure.structure.structure_characterisation_def import (
    StructureCharacterisationDefinitionNames,
)

SQLITE_DEPLOY_CAPABILITIES = ConnectorDeployCapabilities(
    dialect=resolve_sqlglot_dialect("sqlite"),
    # SQLite ALTER TABLE only adds, renames and drops columns: a type,
    # nullability or default change goes through the rebuild strategy.
    alter_add_primary_key=False,
    alter_column_set_default=False,
    alter_column_type=False,
    add_column_positioned=False,
    comparable_characterisations=[
        StructureCharacterisationDefinitionNames.INDEX,
        StructureCharacterisationDefinitionNames.PRIMARY_KEY,
        StructureCharacterisationDefinitionNames.UNIQUE,
    ],
    comparable_data_type_aliases=(
        SQLITE_CONNECTOR_DEFINITION.comparable_data_type_aliases
    ),
    # Views are parsed from their stored definition, so the deploy can
    # protect the ones depending on a table it is about to change.
    detects_dependent_views=True,
    enforce_field_order_default=False,
    rename_column_in_place=True,
    rename_table_in_place=True,
)
