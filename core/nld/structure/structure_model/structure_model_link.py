from typing import Any

from pydantic import Field, field_validator

from nld.pydantic import NldEntityReference, NldNamedBaseModel
from nld.structure.structure.structure import Structure

from .structure_model_cardinality import StructureModelCardinality


class StructureModelLink(NldNamedBaseModel):
    """A directional link between two structures with field-level mappings.

    Each entry in field_mappings pairs one left field to one right field.

    Example YAML:
        left_structure: source.orders
        right_structure: source.customers
        cardinality: many_to_one
        field_mappings:
            customer_id: id
    """

    attributes: dict[str, Any] | None = Field(
        default=None,
        description="Additional metadata for the link",
    )
    cardinality: StructureModelCardinality = Field(
        description="Relationship cardinality between left and right structures",
    )
    condition: str | None = Field(
        default=None,
        description="Optional filter expression for conditional relationships",
    )
    field_mappings: dict[str, str] = Field(
        description="Mapping of left field names to right field names",
    )
    left_structure: NldEntityReference[Structure] = Field(
        description="Reference to the left structure",
    )
    right_structure: NldEntityReference[Structure] = Field(
        description="Reference to the right structure",
    )

    @field_validator("field_mappings", mode="before")
    @classmethod
    def validate_field_mappings_not_empty(cls, value: dict[str, str]) -> dict[str, str]:
        """Ensures that at least one field mapping is provided."""
        if not value:
            raise ValueError("field_mappings must contain at least one mapping")
        return value
