from typing import Any

from pydantic import Field, field_validator

from nld.misc import ValidationFinding
from nld.pydantic import NldNamedBaseModel, NldNamespacedBaseModelWrapper

from .structure_model_link import StructureModelLink


class StructureModelValidationFinding(ValidationFinding):
    """A single structure model validation finding.

    Adds the offending link, mapped field and side (``left``/``right``) on top
    of the shared ValidationFinding context; ``entity`` holds the model name.
    """

    link: str = Field(
        description="Name of the link the finding is about",
    )
    field_name: str = Field(
        description="Name of the offending mapped field",
    )
    side: str = Field(
        description="Side of the mapping the field belongs to (left or right)",
    )

    def get_subject(self) -> str:
        """Locate the finding on its link side and field."""
        return f"{self.link}.{self.side}.{self.field_name}"


class StructureModel(NldNamedBaseModel):
    """Describes inter-structure relationships, cardinality, and conditional links.

    A StructureModel groups multiple links that define how structures
    interact with each other through field-level mappings.

    Example YAML:
        name: order_customer_model
        description: Relates orders to customers
        links:
            order_to_customer:
                left_structure: source.orders
                right_structure: source.customers
                cardinality: many_to_one
                left_to_right_mappings:
                    - {left: customer_id, right: id}
    """

    description: str | None = Field(
        default=None,
        description="Description of the structure model",
    )
    links: dict[str, StructureModelLink] = Field(
        default={},
        description="Named links between structures",
    )

    @field_validator("links", mode="before")
    @classmethod
    def set_link_names_from_keys(
        cls,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        """Sets StructureModelLink.name from the dict key when missing."""
        if value is None:
            return {}
        for key, link in value.items():
            if isinstance(link, dict):
                link.setdefault("name", key)
            elif isinstance(link, StructureModelLink) and link.name != key:
                link.name = key
        return value

    def get_link(self, link_name: str) -> StructureModelLink:
        """Returns a link by name."""
        if link_name not in self.links:
            raise KeyError(
                f"Link '{link_name}' not found in structure model '{self.name}'"
            )
        return self.links[link_name]

    def get_links(self) -> list[StructureModelLink]:
        """Returns all links as a list."""
        return list(self.links.values())

    def get_link_names(self) -> list[str]:
        """Returns all link names."""
        return list(self.links.keys())

    def has_link(self, link_name: str) -> bool:
        """Checks whether a link exists."""
        return link_name in self.links

    def validate_mappings(self) -> list[StructureModelValidationFinding]:
        """Validates join-key mappings against resolved structures.

        Resolves each link's left and right structures and checks that
        every column in left_to_right_mappings exists in the corresponding
        structure. Requires an active NldExecutionContext with a loaded
        entity registry.

        Returns:
            The list of findings; empty when every mapping is valid.
        """
        from nld.service.nld_entity_registry import EntityTypeNames

        findings: list[StructureModelValidationFinding] = []
        for link_name, link in self.links.items():
            left_structure = link.left_structure.resolve(
                entity_type=EntityTypeNames.STRUCTURE,
            )
            right_structure = link.right_structure.resolve(
                entity_type=EntityTypeNames.STRUCTURE,
            )

            left_field_names = left_structure.get_field_names()
            right_field_names = right_structure.get_field_names()

            for mapping in link.left_to_right_mappings:
                left_field = mapping.left
                right_field = mapping.right
                if left_field not in left_field_names:
                    findings.append(
                        StructureModelValidationFinding(
                            entity=self.name,
                            link=link_name,
                            field_name=left_field,
                            side="left",
                            message=(
                                f"Link '{link_name}': left field '{left_field}' "
                                f"not found in structure '{left_structure.name}'"
                            ),
                        )
                    )
                if right_field not in right_field_names:
                    findings.append(
                        StructureModelValidationFinding(
                            entity=self.name,
                            link=link_name,
                            field_name=right_field,
                            side="right",
                            message=(
                                f"Link '{link_name}': right field '{right_field}' "
                                f"not found in structure '{right_structure.name}'"
                            ),
                        )
                    )
        return findings


class NamespacedStructureModel(NldNamespacedBaseModelWrapper["StructureModel"]):
    """StructureModel wrapped with namespace information."""
