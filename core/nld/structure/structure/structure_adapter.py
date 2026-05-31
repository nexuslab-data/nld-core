from typing import Any

from nld.logging import log_event_default
from nld.pydantic import NldNamedBaseModel, NldNamespacedBaseModelWrapper
from nld.structure.events import CreatedStructureUsingAdaptation
from nld.structure.field import (
    Field,
    FieldAdapter,
    FieldNamingMapping,
    FieldTemplate,
    FieldTemplateRelativePosition,
)
from nld.structure.service.structure_characterisation_adapter import (
    StructureCharacterisationAdapter,
)
from nld.utils.jinja_utils import (
    render_template,
    render_template_with_none_return_allowed,
)

from .structure import Structure
from .structure_template import StructureTemplate


class StructureAdapter(NldNamedBaseModel):
    """Adapts a source Structure into a new Structure by applying rules."""

    connector_type_rule: str = "{{ original_structure.connector_type }}"
    desc_rule: str = "{{ original_structure.description }}"
    exclude_fields_wo_naming_mapping: bool = False
    field_adapter: FieldAdapter
    field_templates: list[FieldTemplate] = []
    mandatory_parameters: list[str] = []
    name_rule: str = "{{ original_structure.name }}"
    properties_rule: str | None = "copy"
    structure_characterisations_to_include: list[str] | None = None
    template_mapping: dict[str, str | None] | None = None
    type_rule: str = "TABLE"

    def adapt_structure(self, **kwargs: Any) -> Structure:
        """
        Creates a structure based on this template.

        Parameters (standard)
        -----------
            original_structure: the original structure
            field_naming_mapping: field naming mapping (standard mappings)
            field_catalog: dictionary of all standard fields known. If a
                field is to be generated with a target field name available
                in this catalog, the field definition from the catalog
                should be used to create the new field

        Returns
        -----------
            The new structure
        """
        for parameter_name in self.mandatory_parameters:
            if parameter_name not in kwargs.keys():
                raise ValueError(
                    "Parameter "
                    + parameter_name
                    + " is mandatory for creating structure with template : "
                    + self.name
                )

        original_structure_value = (
            kwargs["original_structure"]
            if "original_structure" in kwargs.keys()
            else None
        )
        if original_structure_value is None:
            raise ValueError("original_structure is required for adapt_structure")
        original_structure: Structure = original_structure_value
        field_naming_mapping: FieldNamingMapping = (
            kwargs["field_naming_mapping"]
            if "field_naming_mapping" in kwargs.keys()
            else FieldNamingMapping()
        )
        field_catalog: dict[str, Field] = (
            kwargs["field_catalog"] if "field_catalog" in kwargs.keys() else {}
        )

        namespace = kwargs.get("namespace")
        creation_param_dict: dict[str, Any] = {
            "namespace": namespace,
            "original_structure": original_structure,
        }

        new_structure = Structure(
            name=render_template(self.name_rule, **creation_param_dict),
            connector_type=render_template_with_none_return_allowed(
                self.connector_type_rule,
                **creation_param_dict,
            ),
            description=render_template_with_none_return_allowed(
                self.desc_rule,
                **creation_param_dict,
            ),
            fields={},
            properties=self._resolve_properties(original_structure),
            stats={"row_count": 0},
            structure_type=render_template(
                self.type_rule,
                **creation_param_dict,
            ),
            templates=self._resolve_templates(original_structure),
        )

        target_from_source_field_naming_mapping_dict = {}
        for field in original_structure.fields.values():
            if self.field_adapter.should_field_be_adapted(field):
                if (not self.exclude_fields_wo_naming_mapping) | (
                    field.name in field_naming_mapping.get_fields_mapped()
                ):
                    new_field = self.field_adapter.adapt_field(
                        original_field=field,
                        field_naming_mapping=field_naming_mapping,
                        field_catalog=field_catalog,
                    )
                    target_from_source_field_naming_mapping_dict.update(
                        {new_field.name: field.name}
                    )
                    new_structure.add_field(new_field)

        self._update_structure_from_template_fields(new_structure)

        if self.structure_characterisations_to_include:
            for characterisation_type in self.structure_characterisations_to_include:
                for characterisation in original_structure.get_characterisations_by(
                    characterisation_type
                ):
                    adapter = StructureCharacterisationAdapter
                    new_characterisation = adapter.adapt_structure_characterisation(
                        characterisation,
                        target_from_source_field_naming_mapping_dict,
                        new_structure.name,
                    )
                    new_structure.add_characterisation(new_characterisation)

        log_event_default(
            CreatedStructureUsingAdaptation(
                structure_name=new_structure.name,
                adapter_name=self.name,
                original_structure_name=original_structure.name,
            )
        )
        return new_structure

    def _resolve_properties(
        self,
        original_structure: Structure,
    ) -> dict[str, str] | None:
        """Resolves properties for the adapted structure."""
        if self.properties_rule == "copy":
            properties = original_structure.get_properties()
            return dict(properties) if properties else None
        return None

    def _resolve_templates(
        self,
        original_structure: Structure,
    ) -> list[StructureTemplate]:
        """Resolves templates for the adapted structure using template_mapping."""
        if self.template_mapping is None:
            return list(original_structure.templates)
        result: list[StructureTemplate] = []
        for template in original_structure.templates:
            if template.name in self.template_mapping:
                new_name = self.template_mapping[template.name]
                if new_name is not None:
                    result.append(
                        StructureTemplate(
                            name=new_name,
                            field_templates=template.field_templates,
                            properties=template.properties,
                            tags=template.tags,
                        )
                    )
            else:
                result.append(template)
        return result

    # Field Template methods
    def get_field_templates_with_existing_override_on_characterisation(
        self,
    ) -> list[FieldTemplate]:
        return [
            field_template
            for field_template in self.field_templates
            if field_template.override_existing_field_on_characterisation is not None
        ]

    def get_field_templates_at_start(self) -> list[FieldTemplate]:
        return [
            field_rule
            for field_rule in self.field_templates
            if field_rule.relative_position == FieldTemplateRelativePosition.START
        ]

    def get_field_templates_at_end(self) -> list[FieldTemplate]:
        return [
            field_rule
            for field_rule in self.field_templates
            if field_rule.relative_position == FieldTemplateRelativePosition.END
        ]

    def _update_structure_from_template_fields(self, structure: Structure) -> None:
        """
        Updates a structure using template field rules

        Parameters
        -----------
            structure : the Data Structure to update
        """
        if self.field_templates is not None:
            """Remove existing field when override required"""
            for (
                field_template
            ) in self.get_field_templates_with_existing_override_on_characterisation():
                override = field_template.override_existing_field_on_characterisation
                assert override is not None
                characterisation_value = override.characterisation
                for field_to_remove in structure.get_fields_with_characterisation(
                    characterisation_value
                ):
                    structure.remove_field(field_to_remove.name)

            # Add field templates at start (insert in order at beginning)
            for index, field_template in enumerate(self.get_field_templates_at_start()):
                field_to_add = field_template.get_field_instance()
                structure.add_field(new_field=field_to_add, index=index)

            # Add field templates at end (append)
            for field_template in self.get_field_templates_at_end():
                structure.add_field(new_field=field_template.get_field_instance())


class NamespacedStructureAdapter(NldNamespacedBaseModelWrapper[StructureAdapter]):
    """StructureAdapter wrapped with namespace information."""
