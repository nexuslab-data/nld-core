from typing import Any

from pydantic import Field, field_validator

from nld.pydantic import NldNamedBaseModel, NldNamespacedBaseModelWrapper

from .structure_model_link import StructureModelLink


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
                field_mappings:
                    customer_id: id
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

    def _is_valid(self) -> list[str]:
        """Validates field mappings against resolved structures.

        Resolves each link's left and right structures and checks that
        every field name in field_mappings exists in the corresponding
        structure. Requires an active NldExecutionContext with a loaded
        entity registry.

        Returns:
            A list of validation error messages. Empty if valid.
        """
        from nld.service.nld_entity_registry import EntityTypeNames

        errors: list[str] = []
        for link_name, link in self.links.items():
            left_structure = link.left_structure.resolve(
                entity_type=EntityTypeNames.STRUCTURE,
            )
            right_structure = link.right_structure.resolve(
                entity_type=EntityTypeNames.STRUCTURE,
            )

            left_field_names = left_structure.get_field_names()
            right_field_names = right_structure.get_field_names()

            for left_field, right_field in link.field_mappings.items():
                if left_field not in left_field_names:
                    errors.append(
                        f"Link '{link_name}': left field '{left_field}' "
                        f"not found in structure '{left_structure.name}'"
                    )
                if right_field not in right_field_names:
                    errors.append(
                        f"Link '{link_name}': right field '{right_field}' "
                        f"not found in structure '{right_structure.name}'"
                    )
        return errors


class NamespacedStructureModel(NldNamespacedBaseModelWrapper["StructureModel"]):
    """StructureModel wrapped with namespace information."""
