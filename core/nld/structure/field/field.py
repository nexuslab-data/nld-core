from typing import Any, cast

from pydantic import Field as PydanticField
from pydantic import field_validator, model_validator

from nld.pydantic import NldBaseModel, NldNamedBaseModel, NldNamespacedBaseModelWrapper
from nld.structure.events import FieldCharacterisationAlreadySet
from nld.utils import NldStrEnum

from .field_characterisation import (
    FieldCharacterisation,
)
from .field_characterisation_definition import (
    FieldCharacterisationDefinitionNames,
)
from .field_data_type import FieldDataType


class FieldTemplateLineageRule(NldBaseModel):
    """A single lineage rule with expression or source_characterisation.

    At most one of expression or source_characterisation can be set.
    expression provides a raw SQL expression (e.g. "CURRENT_TIMESTAMP").
    source_characterisation cross-references a characterisation name
    in the source structure to resolve the source field.
    """

    expression: str | None = PydanticField(
        default=None,
        description="Raw SQL expression for this field (e.g. CURRENT_TIMESTAMP)",
    )
    source_characterisation: str | None = PydanticField(
        default=None,
        description="Characterisation name to cross-reference in source structure",
    )

    @model_validator(mode="after")
    def validate_at_most_one_field_set(self) -> "FieldTemplateLineageRule":
        """Ensure at most one of expression or source_characterisation is set."""
        count = sum(
            [
                self.expression is not None,
                self.source_characterisation is not None,
            ]
        )
        if count > 1:
            raise ValueError(
                "At most one of 'expression' or 'source_characterisation' "
                "can be set on FieldTemplateLineageRule, not both."
            )
        return self


class FieldTemplateLineage(NldBaseModel):
    """Defines how a template field is populated during SQL rendering.

    The default rule is defined by expression and source_characterisation.
    Optional structure_type_overrides provides per-target-type rules
    that take precedence over the default when the target structure
    type matches.
    """

    expression: str | None = PydanticField(
        default=None,
        description="Raw SQL expression for this field (e.g. CURRENT_TIMESTAMP)",
    )
    source_characterisation: str | None = PydanticField(
        default=None,
        description="Characterisation name to cross-reference in source structure",
    )
    structure_type_overrides: dict[str, FieldTemplateLineageRule] | None = (
        PydanticField(
            default=None,
            description="Per-target-structure-type lineage overrides (e.g. VIEW)",
        )
    )

    @model_validator(mode="after")
    def validate_at_most_one_field_set(self) -> "FieldTemplateLineage":
        """Ensure at most one of expression or source_characterisation is set."""
        count = sum(
            [
                self.expression is not None,
                self.source_characterisation is not None,
            ]
        )
        if count > 1:
            raise ValueError(
                "At most one of 'expression' or 'source_characterisation' "
                "can be set on FieldTemplateLineage, not both."
            )
        return self

    @field_validator("structure_type_overrides", mode="before")
    @classmethod
    def normalize_structure_type_override_keys(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Normalize override keys to uppercase."""
        if value is None:
            return value
        return {key.upper(): val for key, val in value.items()}

    def resolve_for_target_type(
        self,
        target_type: str | None,
    ) -> FieldTemplateLineageRule:
        """Return the override rule for target_type if present, else the default."""
        if target_type and self.structure_type_overrides:
            normalized = target_type.upper()
            if normalized in self.structure_type_overrides:
                return self.structure_type_overrides[normalized]
        return FieldTemplateLineageRule(
            expression=self.expression,
            source_characterisation=self.source_characterisation,
        )


class FieldTemplateRelativePosition(NldStrEnum):
    START = "start"
    END = "end"


class FieldTemplate(NldNamedBaseModel):
    """Reusable field definition materialised into structures.

    The embedded field is annotated as a deferred "Field" reference
    because Field itself references FieldTemplate; keeping the deferred
    side here leaves Field fully built at import time, which the
    reference-resolution machinery requires when it inspects
    Field.model_fields before any validation happened.
    """

    field: "Field" = PydanticField(description="Field definition for this template")
    lineage: FieldTemplateLineage | None = PydanticField(
        default=None,
        description="How this template field is populated during SQL rendering",
    )
    override_existing_field_on_characterisation: FieldCharacterisation | None = (
        PydanticField(
            default=None,
            description="Override existing field with this characterisation",
        )
    )
    relative_position: str = PydanticField(
        default=FieldTemplateRelativePosition.END,
        description="Relative position where the field should be placed",
    )

    @model_validator(mode="before")
    @classmethod
    def transform_input_data(cls, data: dict[str, Any]) -> dict[str, Any]:
        """
        Propagates template name to nested field to prevent duplication in YAML.

        This allows users to omit field.name when it matches the template name,
        avoiding redundant repetition in configuration files.
        """
        if not isinstance(data, dict):
            return data

        if "field" in data and isinstance(data["field"], dict):
            field_data = data["field"]
            if "name" not in field_data and "name" in data:
                field_data["name"] = data["name"]

        return data

    @field_validator("relative_position", mode="before")
    @classmethod
    def normalize_relative_position(cls, value: str) -> str:
        """Normalizes relative_position to lowercase."""
        return value.lower() if value else value

    def get_field_instance(self) -> "Field":
        """Get a field instance for this field template."""
        return Field.deep_copy(self.field)


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
    field_template: FieldTemplate | None = PydanticField(
        default=None,
        description="Field template this field is materialised from",
    )

    @model_validator(mode="before")
    @classmethod
    def transform_input_data(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Transforms input data for compact data_type parsing."""
        if not isinstance(data, dict):
            return data

        data = cls._materialize_from_field_template(data=data)

        data_type = data.get("data_type", "")
        if isinstance(data_type, str) and data_type:
            parsed = FieldDataType.from_string(data_type)
            data["data_type"] = parsed.data_type
            if "length" not in data or data["length"] == 0:
                data["length"] = parsed.length
            if "precision" not in data or data["precision"] == 0:
                data["precision"] = parsed.precision

        return data

    @classmethod
    def _materialize_from_field_template(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Materializes the field from its referenced field template.

        The template's embedded field provides the base attributes and any
        key explicitly declared on the field overrides them, so a field can
        be fully template-based while still overriding e.g. the description.
        The merge is idempotent: re-validating an already materialised field
        yields the same result.
        """
        template_value = data.get("field_template")
        if template_value is None:
            return data

        if isinstance(template_value, str):
            raise ValueError(
                f"Field template '{template_value}' could not be resolved. "
                "Ensure field template entities are loaded and the "
                "referenced name exists in the namespace hierarchy."
            )

        template_dict: dict[str, Any] = (
            template_value.model_dump()
            if isinstance(template_value, NldBaseModel)
            else dict(template_value)
        )
        template_field: dict[str, Any] = dict(template_dict.get("field") or {})

        declared = {
            key: value for key, value in data.items() if key != "field_template"
        }

        # A declared compact data_type carries its own length/precision, so
        # the template's physical sizing must not leak into the override.
        if "data_type" in declared:
            template_field.pop("length", None)
            template_field.pop("precision", None)

        merged = template_field
        merged.update(declared)
        merged["field_template"] = template_value
        return merged

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


class NamespacedFieldTemplate(NldNamespacedBaseModelWrapper[FieldTemplate]):
    """FieldTemplate wrapped with namespace information."""
