from typing import Any

from pydantic import Field as PydanticField
from pydantic import field_validator, model_validator

from nld.pydantic import NldBaseModel, NldNamedBaseModel, NldNamespacedBaseModelWrapper
from nld.utils import NldStrEnum

from .field import Field
from .field_characterisation import FieldCharacterisation


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
    field: Field = PydanticField(description="Field definition for this template")
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

    def get_field_instance(self) -> Field:
        """Get a field instance for this field template."""
        return Field.deep_copy(self.field)


class NamespacedFieldTemplate(NldNamespacedBaseModelWrapper[FieldTemplate]):
    """FieldTemplate wrapped with namespace information."""
