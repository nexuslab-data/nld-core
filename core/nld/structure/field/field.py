from typing import Any, cast

from pydantic import Field as PydanticField
from pydantic import field_validator, model_validator

from nld.pydantic import NldNamedBaseModel, NldNamespacedBaseModelWrapper
from nld.structure.events import FieldCharacterisationAlreadySet

from .field_characterisation import (
    FieldCharacterisation,
)
from .field_characterisation_definition import (
    FieldCharacterisationDefinitionNames,
)
from .field_data_type import FieldDataType


class Field(NldNamedBaseModel):
    description: str | None = PydanticField(
        default=None,
        description="Description of the field",
    )
    short_description: str | None = PydanticField(
        default=None,
        description="Short description for display purposes",
    )
    data_type: str = PydanticField(
        default="",
        description="Data type of the field",
    )
    length: int = PydanticField(
        default=0,
        description="Length of the field",
    )
    precision: int = PydanticField(
        default=0,
        description="Precision of the field",
    )
    default_value: str | int | None = PydanticField(
        default=None,
        description="Default value for the field",
    )
    characterisations: list[FieldCharacterisation] = PydanticField(
        default=[],
        description="List of characterisations for this field",
    )
    fields: dict[str, "Field"] = PydanticField(
        default={},
        description="Sub-fields for nested types (VARIANT, OBJECT, ARRAY)",
    )

    @model_validator(mode="before")
    @classmethod
    def transform_input_data(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Transforms input data for compact data_type parsing."""
        if not isinstance(data, dict):
            return data

        data_type = data.get("data_type", "")
        if isinstance(data_type, str) and data_type:
            parsed = FieldDataType.from_string(data_type)
            data["data_type"] = parsed.data_type
            if "length" not in data or data["length"] == 0:
                data["length"] = parsed.length
            if "precision" not in data or data["precision"] == 0:
                data["precision"] = parsed.precision

        return data

    @field_validator("fields", mode="before")
    @classmethod
    def set_sub_field_names_from_keys(
        cls,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        """Sets sub-field name from dict key if not already present."""
        for key, field_data in value.items():
            if isinstance(field_data, Field):
                continue
            if field_data is None:
                field_data = {}
                value[key] = field_data
            if "name" not in field_data:
                field_data["name"] = key
        return value

    @field_validator("characterisations", mode="before")
    @classmethod
    def ensure_characterisations_not_none(
        cls, value: list[FieldCharacterisation] | None
    ) -> list[FieldCharacterisation]:
        """Ensures characterisations is never None."""
        return value if value is not None else []

    # Characterisation methods
    def get_characterisations(self) -> list[FieldCharacterisation]:
        return self.characterisations

    def get_characterisation_names(self) -> list[str]:
        """Returns list of characterisations (not instance names)."""
        return [char.characterisation for char in self.get_characterisations()]

    def get_characterisation(
        self, characterisation: str
    ) -> FieldCharacterisation | None:
        """Gets a characterisation by its characterisation value.

        Args:
            characterisation: The characterisation to look for.

        Returns:
            The FieldCharacterisation if found, None otherwise.
        """
        for char in self.get_characterisations():
            if char.characterisation == characterisation:
                return char
        return None

    def has_characterisations(self) -> bool:
        """Checks if this field has any characterisations."""
        return len(self.characterisations) > 0

    def has_characterisation(self, characterisation: str) -> bool:
        """Checks if this field has the requested characterisation."""
        return characterisation in self.get_characterisation_names()

    def has_one_of_characterisations(self, characterisations: list[str]) -> bool:
        """Checks if this field has one of the requested characterisations."""
        return any(
            char in characterisations for char in self.get_characterisation_names()
        )

    def add_characterisation(self, new_char: str | FieldCharacterisation) -> None:
        """Adds characterisation to the field if it does not already exist.

        Args:
            new_char: The characterisation to add, either as a string or
                FieldCharacterisation object.
        """
        char_to_add = (
            new_char
            if type(new_char) is FieldCharacterisation
            else FieldCharacterisation(
                name=cast(str, new_char),
                characterisation=cast(str, new_char),
            )
        )
        if self.has_characterisation(char_to_add.characterisation):
            self.log_event(
                FieldCharacterisationAlreadySet(self.name, char_to_add.characterisation)
            )
            return
        self.characterisations.append(char_to_add)

    def remove_characterisation(self, characterisation: str) -> None:
        """Removes characterisation from the field.

        Args:
            characterisation: The characterisation to remove.
        """
        if characterisation is None:
            return
        if characterisation not in self.get_characterisation_names():
            return
        for char_lcl in self.characterisations:
            if char_lcl.characterisation == characterisation:
                self.characterisations.remove(char_lcl)
                break

    # Standard field characterisation methods
    def is_mandatory(self) -> bool:
        return self.has_characterisation(FieldCharacterisationDefinitionNames.MANDATORY)

    def set_mandatory(self) -> None:
        self.add_characterisation(FieldCharacterisationDefinitionNames.MANDATORY)

    def unset_mandatory(self) -> None:
        self.remove_characterisation(FieldCharacterisationDefinitionNames.MANDATORY)

    def is_unique(self) -> bool:
        return self.has_characterisation(FieldCharacterisationDefinitionNames.UNIQUE)

    def set_unique(self) -> None:
        self.add_characterisation(FieldCharacterisationDefinitionNames.UNIQUE)

    def unset_unique(self) -> None:
        self.remove_characterisation(FieldCharacterisationDefinitionNames.UNIQUE)

    def is_last_update_tst(self) -> bool:
        return self.has_characterisation(
            FieldCharacterisationDefinitionNames.REC_LAST_UPDATE_TST
        )

    def is_insert_tst(self) -> bool:
        return self.has_characterisation(
            FieldCharacterisationDefinitionNames.REC_INSERT_TST
        )

    def is_source_last_update_tst(self) -> bool:
        return self.has_characterisation(
            FieldCharacterisationDefinitionNames.REC_SOURCE_LAST_UPDATE_TST
        )

    # Sub-field methods
    def get_fields(self) -> dict[str, "Field"]:
        """Returns the sub-fields dictionary."""
        return self.fields

    def get_field_names(self) -> list[str]:
        """Returns list of sub-field names."""
        return list(self.fields.keys())

    def get_field(self, name: str) -> "Field":
        """Gets a sub-field by name.

        Args:
            name: The sub-field name to look for.

        Returns:
            The Field if found.

        Raises:
            KeyError: If the sub-field is not found.
        """
        return self.fields[name]

    def has_field(self, name: str) -> bool:
        """Checks if this field has a sub-field with the given name."""
        return name in self.fields

    def has_fields(self) -> bool:
        """Checks if this field has any sub-fields."""
        return len(self.fields) > 0


class NamespacedField(NldNamespacedBaseModelWrapper[Field]):
    """Field wrapped with namespace information."""
