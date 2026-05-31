from typing import Any

from pydantic import Field, field_validator, model_validator

from nld.pydantic import NldNamedBaseModel

from .field_characterisation_def import (
    FieldCharacterisationDefinition,
)


class FieldCharacterisation(NldNamedBaseModel):
    characterisation: str = Field(
        description="The characterisation type",
    )
    attributes: dict[str, Any] | None = Field(
        default=None,
        description="Additional attributes for this characterisation",
    )

    @model_validator(mode="before")
    @classmethod
    def parse_characterisation_formats(cls, data: Any) -> dict[str, Any]:
        """
        Parses characterisation formats into standard dict format.

        Format 1 (full object): {"name": "pk_field", "characterisation": "primary_key"}
            -> passed through
        String format (FieldCharacterisation only): "mandatory"
            -> {"name": "mandatory", "characterisation": "mandatory"}
        """
        if isinstance(data, str):
            char_value = data.lower()
            return {"name": char_value, "characterisation": char_value}

        if not isinstance(data, dict):
            return data  # type: ignore[no-any-return]

        return data

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """Normalizes characterisation name to lowercase."""
        return value.lower() if value else value

    @field_validator("characterisation", mode="before")
    @classmethod
    def normalize_characterisation(cls, value: str) -> str:
        """Normalizes characterisation type to lowercase."""
        return value.lower() if value else value

    def has_attributes(self) -> bool:
        return self.attributes is not None and len(self.attributes) > 0

    @classmethod
    def create_from_definition(
        cls, definition: FieldCharacterisationDefinition
    ) -> "FieldCharacterisation":
        return FieldCharacterisation(
            characterisation=definition.name,
            name=definition.name,
        )
