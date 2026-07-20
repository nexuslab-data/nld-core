from typing import Any

from pydantic import Field, field_validator, model_validator

from nld.pydantic import NldBaseModel, NldEntityReference, NldNamedBaseModel
from nld.structure.structure.structure import Structure

from .structure_model_cardinality import StructureModelCardinality


class StructureModelColumnMapping(NldBaseModel):
    """A single left -> right column pairing in a structure-model link.

    Accepts a shorthand string when the column name is identical on both
    sides (e.g. ``organization_reference``), or an explicit ``{left, right}``
    pair when the names differ (e.g. ``{left: cd_job_reference, right:
    job_reference}``).
    """

    left: str = Field(description="Column name on the left structure")
    right: str = Field(description="Column name on the right structure")

    @model_validator(mode="before")
    @classmethod
    def _expand_shorthand(cls, data: Any) -> Any:
        """Expand a bare string into an identical left/right pair."""
        if isinstance(data, str):
            return {"left": data, "right": data}
        return data


class StructureModelLink(NldNamedBaseModel):
    """A directional link between two structures with join-key mappings.

    ``left_to_right_mappings`` lists the join keys pairing one left column to
    one right column. Each entry is a single column name when it is identical
    on both sides, or a ``{left, right}`` pair when the names differ.

    Example YAML:
        left_structure: source.orders
        right_structure: source.customers
        cardinality: many_to_one
        left_to_right_mappings:
            - {left: customer_id, right: id}
            - organization_reference        # identical on both sides
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
    left_to_right_mappings: list[StructureModelColumnMapping] = Field(
        description=(
            "Join column mappings from the left structure to the right "
            "structure. Each entry is a single column name when identical on "
            "both sides, or a {left, right} pair when the names differ."
        ),
    )
    left_structure: NldEntityReference[Structure] = Field(
        description="Reference to the left structure",
    )
    right_structure: NldEntityReference[Structure] = Field(
        description="Reference to the right structure",
    )

    @field_validator("left_to_right_mappings", mode="before")
    @classmethod
    def validate_mappings_not_empty(cls, value: Any) -> Any:
        """Ensures that at least one column mapping is provided."""
        if not value:
            raise ValueError("left_to_right_mappings must contain at least one mapping")
        return value
