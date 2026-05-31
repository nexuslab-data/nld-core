from typing import Literal

from nld.logging import NldLoggable
from nld.pydantic import NldBaseModel, NldNamedBaseModel
from nld.utils.string_utils import un_camel

"""
Entity search direction behavior.

Determines how entity lookups traverse the namespace hierarchy:
- "children": Search from the given namespace into its child namespaces.
  When duplicates exist, the entity closest to root takes priority.
  Use for entities that are defined at higher levels and inherited downward.
- "parents": Search from the given namespace into its parent namespaces.
  When duplicates exist, the entity closest to the current namespace takes priority.
  Use for entities that should be inherited from parent namespaces (e.g., config).
"""

SearchDirection = Literal["children", "parents"]

SEARCH_DIRECTION_CHILDREN: SearchDirection = "children"
SEARCH_DIRECTION_PARENTS: SearchDirection = "parents"
SEARCH_DIRECTIONS = [SEARCH_DIRECTION_CHILDREN, SEARCH_DIRECTION_PARENTS]

"""
Entity category constants for grouping in display.

Categories allow organizing entity types into logical groups for better
display and management. Each entity definition can be assigned a category
to indicate its functional purpose.
"""

ENTITY_CATEGORY_CONFIGURATION = "Configuration"
ENTITY_CATEGORY_DATA_FLOW = "Data Flow"
ENTITY_CATEGORY_STRUCTURE = "Structure"
ENTITY_CATEGORY_STRUCTURE_CONFIGURATION = "Structure Configuration"
ENTITY_CATEGORY_VOCABULARY = "Vocabulary"

ENTITY_CATEGORIES = [
    ENTITY_CATEGORY_CONFIGURATION,
    ENTITY_CATEGORY_DATA_FLOW,
    ENTITY_CATEGORY_STRUCTURE,
    ENTITY_CATEGORY_STRUCTURE_CONFIGURATION,
    ENTITY_CATEGORY_VOCABULARY,
]

ENTITY_CATEGORY_DISPLAY_ORDER: dict[str, int] = {
    ENTITY_CATEGORY_CONFIGURATION: 1,
    ENTITY_CATEGORY_DATA_FLOW: 4,
    ENTITY_CATEGORY_STRUCTURE: 2,
    ENTITY_CATEGORY_STRUCTURE_CONFIGURATION: 3,
    ENTITY_CATEGORY_VOCABULARY: 5,
}


class EntityDefinition(NldLoggable):
    """Defines an entity type with its model and loading configuration."""

    def __init__(
        self,
        name: str,
        model_type: type[NldNamedBaseModel] | type[NldBaseModel],
        folder_name: str,
        file_format: str = "yaml",
        search_direction: SearchDirection = SEARCH_DIRECTION_CHILDREN,
        category: str | None = None,
        display_name: str | None = None,
    ):
        super().__init__()
        if file_format not in ["yaml", "jinja"]:
            raise ValueError(
                "Invalid file_format: file_format must be one of ['yaml', 'jinja']"
            )
        if search_direction not in SEARCH_DIRECTIONS:
            directions = ", ".join(SEARCH_DIRECTIONS)
            raise ValueError(f"Invalid search_direction: must be one of {directions}")
        self.category = category
        self.display_name = display_name
        self.file_format = file_format
        self.folder_name = folder_name
        self.model_type = model_type
        self.name = name
        self.search_direction: SearchDirection = search_direction

    def get_model_type_name(self) -> str:
        """Get the un-camelized name of the model type."""
        return un_camel(self.model_type.__name__)

    def is_named_model(self) -> bool:
        """Check if the model type is a named model."""
        return issubclass(self.model_type, NldNamedBaseModel)
