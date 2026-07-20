from typing import TYPE_CHECKING

from pydantic import Field

from nld.misc import ValidationFinding
from nld.structure.field.field_characterisation_definition import (
    FIELD_CHARACTERISATION_DEFINITIONS,
    FieldCharacterisationDefinition,
)

if TYPE_CHECKING:
    from nld.service.nld_entity_registry import NldEntityRegistry


class CharacterisationValidationFinding(ValidationFinding):
    """A single field characterisation validation finding.

    Adds the offending field and characterisation token on top of the shared
    ValidationFinding context; ``entity`` holds the structure name and the
    ``message`` describes the problem (an unknown characterisation, a forbidden
    attribute, or a single-field characterisation used on several fields).
    """

    field_name: str = Field(
        description="Name of the offending field(s)",
    )
    characterisation: str = Field(
        description="The characterisation token involved in the finding",
    )

    def get_subject(self) -> str:
        """Locate the finding on its offending field."""
        return self.field_name


def resolve_field_characterisation_definitions(
    registry: "NldEntityRegistry",
    namespace: str | None = None,
) -> dict[str, FieldCharacterisationDefinition]:
    """Merge built-in default definitions with project-declared ones.

    Built-in code defaults are the base catalogue; project definitions visible
    from ``namespace`` are overlaid on top, so a project declaration overrides a
    built-in of the same (case-insensitive) name. Keys are the lowercase
    characterisation token, matching what fields actually store.
    """
    catalogue: dict[str, FieldCharacterisationDefinition] = dict(
        FIELD_CHARACTERISATION_DEFINITIONS,
    )
    project_definitions = registry.get_field_characterisation_definition_dict(
        namespace=namespace,
    )
    for wrapper in project_definitions.values():
        catalogue[wrapper.model.name.lower()] = wrapper.model
    return catalogue
