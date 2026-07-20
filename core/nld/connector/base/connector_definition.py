from __future__ import annotations

from nld.pydantic.base_model import NldBaseModel


class ConnectorDefinition(NldBaseModel):
    """Static engine facts shared by the connector's models and services.

    Each connector extends this class once and exposes a singleton
    through ``DataConnector.get_connector_definition``: the models and
    services consult the definition instead of hardcoding engine
    knowledge locally.

    ``accepted_data_types`` lists the engine type spellings a
    structure definition may declare (empty means not restricted).
    ``comparable_data_type_aliases`` carries the engine's own type
    spellings mapped to their canonical comparable form.
    ``fixed_precision_data_types`` lists the types whose precision is
    fixed by the engine and never reported by the readers.
    """

    accepted_data_types: list[str] = []
    comparable_data_type_aliases: dict[str, str] = {}
    fixed_precision_data_types: list[str] = []
    name: str

    def has_fixed_precision(self, data_type: str) -> bool:
        """Check if a data type has a fixed precision that should not be reported."""
        return data_type.upper() in self.fixed_precision_data_types
