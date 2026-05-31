from pydantic import field_validator

from nld.pydantic import NldBaseModel, NldNamedBaseModel
from nld.service.entity_definition import (
    SEARCH_DIRECTION_PARENTS,
    SEARCH_DIRECTIONS,
    EntityDefinition,
    SearchDirection,
)
from nld.utils.import_utils import import_class_inside_module

VALID_FILE_FORMATS = ["yaml", "jinja"]


class AdditionalEntityConfig(NldBaseModel):
    """Configuration for a custom entity type declared in nld_project.yml."""

    category: str | None = None
    display_name: str | None = None
    file_format: str = "yaml"
    folder_name: str
    model_type: str
    name: str
    search_direction: SearchDirection = SEARCH_DIRECTION_PARENTS

    @field_validator("file_format")
    @classmethod
    def validate_file_format(cls, value: str) -> str:
        """Validate file_format is one of the allowed values."""
        if value not in VALID_FILE_FORMATS:
            raise ValueError(
                f"Invalid file_format '{value}': must be one of {VALID_FILE_FORMATS}"
            )
        return value

    @field_validator("model_type")
    @classmethod
    def validate_model_type_format(cls, value: str) -> str:
        """Validate model_type contains a dot (module.ClassName format)."""
        if "." not in value:
            raise ValueError(
                f"Invalid model_type '{value}': "
                "must be a fully qualified Python path "
                "(e.g., 'my_package.models.MyModel')"
            )
        return value

    @field_validator("search_direction")
    @classmethod
    def validate_search_direction(cls, value: str) -> str:
        """Validate search_direction is one of the allowed values."""
        if value not in SEARCH_DIRECTIONS:
            directions = ", ".join(SEARCH_DIRECTIONS)
            raise ValueError(
                f"Invalid search_direction '{value}': must be one of {directions}"
            )
        return value

    def to_entity_definition(self) -> EntityDefinition:
        """Convert this config to an EntityDefinition by resolving the model type."""
        _, resolved_class = import_class_inside_module(self.model_type)

        if not issubclass(resolved_class, NldBaseModel | NldNamedBaseModel):
            raise ValueError(
                f"model_type '{self.model_type}' resolved to "
                f"'{resolved_class.__name__}' which is not a subclass "
                f"of NldBaseModel or NldNamedBaseModel"
            )

        return EntityDefinition(
            name=self.name,
            model_type=resolved_class,
            category=self.category,
            display_name=self.display_name,
            file_format=self.file_format,
            folder_name=self.folder_name,
            search_direction=self.search_direction,
        )
