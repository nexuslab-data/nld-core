from typing import Any

from pydantic import Field, field_validator

from nld.pydantic import NldNamedBaseModel


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
    def normalize_characterisation(cls, value: str) -> str:
        """Normalizes characterisation type to lowercase."""
        return value.lower() if value else value

    def has_attributes(self) -> bool:
        return self.attributes is not None and len(self.attributes) > 0
