from typing import Any

from pydantic import Field, ValidationInfo, field_validator

from nld.pydantic import NldNamedBaseModel, get_source_file_path
from nld.structure.structure.structure_characterisation_def import (
    resolve_structure_characterisation_alias,
)


class StructureCharacterisation(NldNamedBaseModel):
    characterisation: str = Field(
        description="The characterisation type",
    )
    attributes: dict[str, Any] | None = Field(
        default=None,
        description="Additional attributes for this characterisation",
    )
    linked_fields: list[str] | None = Field(
        default=None,
        description="Field names linked to this characterisation",
    )

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """Normalizes characterisation name to lowercase."""
        return value.lower() if value else value

    @field_validator("characterisation", mode="before")
    @classmethod
    def normalize_characterisation(
        cls,
        value: str,
        info: ValidationInfo,
    ) -> str:
        """Normalizes characterisation type to lowercase, resolving aliases.

        A deprecated ``functional_*`` type is replaced by its ``business_*``
        name here, so no code past the parser ever sees the old name.
        """
        if not value:
            return value
        location = f"'{info.data.get('name')}'"
        source_file_path = get_source_file_path(info)
        if source_file_path is not None:
            location = f"{location} ({source_file_path})"
        return resolve_structure_characterisation_alias(
            value.lower(),
            location=location,
        )

    def has_attributes(self) -> bool:
        return self.attributes is not None and len(self.attributes) > 0
