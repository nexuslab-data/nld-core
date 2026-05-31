import abc
from typing import Any

from nld.flow.definition.sql_config import SQLConfig
from nld.flow.sql.sql_rendering import SQLRendering


class SQLRenderingTransformation(SQLRendering, abc.ABC):
    """Abstract base for structure-driven SQL rendering transformations.

    Transformations generate SQL based on Structure metadata
    (characterisations, field types) rather than explicit field
    mappings. They ignore target_from_sources_mapping and derive
    the query structure from the source Structure's semantics.
    """

    def __init__(
        self,
        config: SQLConfig | None = None,
    ) -> None:
        self.config = config

    def _get_parameter(
        self,
        key: str,
    ) -> Any | None:
        """Get a parameter value from the config parameters dict."""
        if self.config is None or self.config.parameters is None:
            return None
        return self.config.parameters.get(key)
