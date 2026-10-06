from typing import Any, cast

from pydantic import field_validator

from nld.exceptions import (
    MissingMandatoryArgumentException,
    NldRuntimeException,
)
from nld.logging import (
    log_error_default,
    log_event_default,
    log_warn_default,
)
from nld.logging.events import MissingMandatoryArgument
from nld.pydantic import NldNamedBaseModel, NldNamespacedBaseModelWrapper
from nld.structure.events import (
    NotAvailableFieldInStructure,
)
from nld.structure.exceptions import (
    FieldAdditionException,
    NotAvailableFieldException,
)
from nld.structure.field import Field
from nld.structure.field.field import (
    FieldTemplateLineage,
    FieldTemplateRelativePosition,
)
from nld.structure.field.field_characterisation_catalog import (
    CharacterisationValidationFinding,
)
from nld.structure.field.field_characterisation_definition import (
    FieldCharacterisationDefinition,
    FieldCharacterisationDefinitionNames,
)

from .structure_characterisation import (
    StructureCharacterisation,
)
from .structure_characterisation_def import (
    STRUCTURE_CHARACTERISATION_DEFINITIONS,
    StructureCharacterisationDefinition,
    StructureCharacterisationDefinitionNames,
)
from .structure_generation_metadata import StructureGenerationMetadata
from .structure_template import StructureTemplate

EXTERNAL_SOURCE_TAG = "external_source"
MANAGED_BY_FLOW_EXECUTION_TAG = "target_structure_is_managed_by_flow_execution"

_STRUCTURE_SUBCLASS_REGISTRY: dict[str, str] = {}


class Structure(NldNamedBaseModel):
    structure_type: str
    class_path: str | None = None
    connector_type: str | None = None
    description: str | None = None
    short_description: str | None = None
    short_name: str | None = None
    stats: dict[str, str | int] | None = None
    templates: list[StructureTemplate] = []
    tags: list[str] = []
    properties: dict[str, str] | None = None
    business_metadata: dict[str, str] | None = None
    origin: dict[str, Any] | None = None
    options: dict[str, Any] | None = None
    post_deployment_sql_hook: list[str] | None = None
    pre_deployment_sql_hook: list[str] | None = None
    enforce_field_order: bool | None = None
    fields: dict[str, Field] = {}
    characterisations: list[StructureCharacterisation] = []
    generation_metadata: StructureGenerationMetadata | None = None

    @classmethod
    def get_registry_attribute_key(cls) -> str | None:
        """Get the entity dict key used for subclass registry lookup."""
        return "connector_type"

    @classmethod
    def register_subclass(
        cls,
        connector_type: str,
        class_path: str,
    ) -> None:
        """Register a Structure subclass for a connector type.

        Args:
            connector_type: The connector type identifier (e.g. "postgresql").
            class_path: Full Python class path for
                dynamic import.
        """
        _STRUCTURE_SUBCLASS_REGISTRY[connector_type] = class_path

    @classmethod
    def get_registered_class_path(cls, connector_type: str) -> str | None:
        """Get the registered class path for a connector type."""
        return _STRUCTURE_SUBCLASS_REGISTRY.get(connector_type)

    @field_validator(
        "pre_deployment_sql_hook", "post_deployment_sql_hook", mode="before"
    )
    @classmethod
    def wrap_string_as_list(cls, value: list[str] | str | None) -> list[str] | None:
        """Normalize a single string into a one-element list."""
        if isinstance(value, str):
            return [value]
        return value

    @field_validator("fields", mode="before")
    @classmethod
    def set_field_names_from_keys(
        cls,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        """Sets field name from dict key if not already present."""
        for key, field_data in value.items():
            if isinstance(field_data, Field):
                continue
            if field_data is None:
                field_data = {}
                value[key] = field_data
            if "name" not in field_data:
                field_data["name"] = key
        return value

    @field_validator("structure_type", mode="before")
    @classmethod
    def normalize_structure_type(cls, value: str) -> str:
        """Normalizes structure type to uppercase."""
        return value.upper() if value else value

    @field_validator("characterisations", mode="before")
    @classmethod
    def ensure_characterisations_not_none(
        cls, value: list[StructureCharacterisation] | None
    ) -> list[StructureCharacterisation]:
        """Ensures characterisations is never None."""
        return value if value is not None else []

    # Structure-level methods
    def is_table(self) -> bool:
        """Checks if the structure is a table."""
        return (
            self.structure_type.upper() == "TABLE"
            if self.structure_type is not None
            else False
        )

    def is_view(self) -> bool:
        """Checks if the structure is a view.

        Accepted values for structure type are: VIEW.
        """
        return (
            self.structure_type.upper() in ["VIEW"]
            if self.structure_type is not None
            else False
        )

    def is_generated(self) -> bool:
        """Checks if the structure was generated by nld structure generate."""
        return self.generation_metadata is not None

    def is_external_source(self) -> bool:
        """Checks if the structure is tagged as an external source."""
        return EXTERNAL_SOURCE_TAG in self.get_all_tags()

    def is_managed_by_flow_execution(self) -> bool:
        """Checks if the structure is managed by the flow execution itself."""
        return MANAGED_BY_FLOW_EXECUTION_TAG in self.get_all_tags()

    # Field-level methods
    def get_fields(self) -> list[Field]:
        """Get the list of fields in their defined order."""
        return list(self.fields.values())

    def get_field_names(self) -> list[str]:
        """Get the list of field names in their defined order.

        Returns:
            The list of the field names.
        """
        return list(self.fields.keys())

    def get_field(self, name: str) -> Field:
        """Get a field based on its name.

        Resolves both the structure's own fields and the fields
        contributed by its referenced templates, so a name pointing at a
        template-provided field (e.g. ``ts_src_extracted_at`` from a
        tracking template) is found. Declared fields take priority over
        template fields with the same name, matching ``get_all_fields``.

        Args:
            name: The field name to look for.

        Returns:
            The field structure with the provided field name.

        Raises:
            NotAvailableFieldException: If the field is not available.
        """
        for field in self.get_all_fields():
            if field.name == name:
                return field
        log_event_default(NotAvailableFieldInStructure(self.name, name))
        raise NotAvailableFieldException(structure_name=self.name, field_name=name)

    def has_field(self, name: str) -> bool:
        """Checks if a field with the provided name is available in the structure.

        Considers both the structure's own fields and template-contributed
        fields, consistently with ``get_field``.
        """
        try:
            self.get_field(name)
        except NotAvailableFieldException:
            return False
        return True

    def get_fields_based_on_names(self, field_names: list[str]) -> list[Field]:
        """Get a list of fields based on their names."""
        return [self.get_field(field_name) for field_name in field_names]

    def get_single_field_with_characterisation(
        self, characterisation: str
    ) -> Field | None:
        """Get a single field with the provided characterisation.

        The first one found is returned.

        Args:
            characterisation: The characterisation to look for.

        Returns:
            The first field with the characterisation, or None if not found.
        """
        found_fields = self.get_fields_with_characterisation(characterisation)
        if len(found_fields) == 0:
            return None
        selected_field = found_fields[0]
        if len(found_fields) > 1:
            log_warn_default(
                f"Multiple fields with characterisation {characterisation} "
                f"found in structure {self.name}: "
                f"{', '.join([field.name for field in found_fields])}"
            )
            log_warn_default(f"First field will be selected: {selected_field.name}")
            return selected_field
        return selected_field

    def get_fields_with_characterisation(self, characterisation: str) -> list[Field]:
        """Get the list of fields with the provided characterisation.

        Args:
            characterisation: The characterisation to look for.

        Returns:
            The list of fields with the provided characterisation.
        """
        return [
            field
            for field in self.get_all_fields()
            if field.has_characterisation(characterisation)
        ]

    def validate_characterisations(
        self,
        catalogue: dict[str, FieldCharacterisationDefinition],
    ) -> list[CharacterisationValidationFinding]:
        """Delegate to the independent StructureCharacterisationChecker.

        The actual checking lives in the standalone checker service so the
        structure stays a pure data object; this is a thin convenience that
        runs the checker over ``self`` with the provided catalogue.
        """
        from nld.structure.service.structure_characterisation_checker import (
            StructureCharacterisationChecker,
        )

        return StructureCharacterisationChecker(catalogue=catalogue).check(
            structure=self,
        )

    def has_field_with_characterisation(self, characterisation: str) -> bool:
        """Check that at least one field has the provided characterisation.

        Args:
            characterisation: The characterisation to look for.

        Returns:
            True if there is at least one field with the characterisation.
        """
        return len(self.get_fields_with_characterisation(characterisation)) > 0

    def get_fields_with_characterisations(
        self, characterisations: list[str]
    ) -> list[Field]:
        """Get the list of fields with any of the provided characterisations.

        Args:
            characterisations: The list of characterisations to look for.

        Returns:
            The list of fields with any of the provided characterisations.
        """
        return [
            field
            for field in self.get_all_fields()
            if any(
                char in characterisations for char in field.get_characterisation_names()
            )
        ]

    def has_field_with_one_of_characterisations(
        self, characterisations: list[str]
    ) -> bool:
        """Check that at least one field has one of the characterisations.

        Args:
            characterisations: The list of characterisations to look for.

        Returns:
            True if there is at least one field with one of the
            characterisations.
        """
        return len(self.get_fields_with_characterisations(characterisations)) > 0

    def get_fields_wo_characterisations(
        self, characterisations: list[str]
    ) -> list[Field]:
        """Get fields without any of the provided characterisations.

        Args:
            characterisations: The list of characterisations to look for.

        Returns:
            The list of fields without any of the provided characterisations.
        """
        excluded_names = {
            field.name
            for field in self.get_fields_with_characterisations(characterisations)
        }
        return [
            field for field in self.get_all_fields() if field.name not in excluded_names
        ]

    def get_field_names_with_characterisation(self, characterisation: str) -> list[str]:
        """Get the list of field names with the provided characterisation.

        Args:
            characterisation: The characterisation to look for.

        Returns:
            The list of field names with the provided characterisation.
        """
        return [
            field.name
            for field in self.get_fields_with_characterisation(characterisation)
        ]

    def get_field_name_with_characterisation(
        self,
        characterisation: str,
        multiple_allowed: bool = False,
        none_throws_exception: bool = False,
    ) -> str | None:
        """Get a single field name with the provided characterisation.

        Args:
            characterisation: The characterisation to look for.
            multiple_allowed: When False, raises ValueError if more than
                one field has the characterisation.
            none_throws_exception: When True, raises ValueError if no
                field with the characterisation is found.

        Returns:
            The field name if found, None otherwise.

        Raises:
            ValueError: If multiple_allowed is False and more than one
                field has the characterisation, or if none_throws_exception
                is True and no field is found.
        """
        field_names = self.get_field_names_with_characterisation(characterisation)
        if len(field_names) == 0:
            if none_throws_exception:
                raise ValueError(
                    f"Structure '{self.name}' has no field with "
                    f"'{characterisation}' characterisation"
                )
            return None
        if not multiple_allowed and len(field_names) > 1:
            raise ValueError(
                f"Expected at most one field with characterisation "
                f"'{characterisation}' in structure '{self.name}', "
                f"found {len(field_names)}: {', '.join(field_names)}"
            )
        return field_names[0]

    def get_field_names_with_characterisations(
        self, characterisations: list[str]
    ) -> list[str]:
        """Get field names with any of the provided characterisations.

        Args:
            characterisations: The list of characterisations to look for.

        Returns:
            The list of field names with any of the characterisations.
        """
        return [
            field.name
            for field in self.get_fields_with_characterisations(characterisations)
        ]

    def get_field_names_wo_characterisations(
        self, characterisations: list[str]
    ) -> list[str]:
        """Get field names without any of the provided characterisations.

        Args:
            characterisations: The list of characterisations to look for.

        Returns:
            The list of field names without any of the characterisations.
        """
        return [
            field.name
            for field in self.get_fields_wo_characterisations(characterisations)
        ]

    def add_field(
        self,
        new_field: Field,
        index: int | None = None,
        previous_field_name: str | None = None,
        next_field_name: str | None = None,
    ) -> None:
        """Adds the provided field to this structure.

        By default, fields are added at the end. Use the optional parameters
        to insert at specific positions.

        Args:
            new_field: The new field to be added.
            index: Insert at this specific index (0-based). Takes priority over
                previous_field_name and next_field_name.
            previous_field_name: Insert after the field with this name.
            next_field_name: Insert before the field with this name.
        """
        if new_field is None:
            log_event_default(
                MissingMandatoryArgument(
                    method_name="Add Field",
                    object_type=type(self),
                    argument_name="New Field",
                )
            )
            raise MissingMandatoryArgumentException(
                method_name="Add Field",
                object_type=type(self),
                argument_name="New Field",
            )

        if index is not None:
            self._insert_field_at_index(new_field, index)
        elif previous_field_name is not None:
            field_index = self._get_field_index(previous_field_name)
            if field_index is None:
                log_event_default(
                    NotAvailableFieldInStructure(
                        field_name=previous_field_name,
                        structure_name=self.name,
                    )
                )
                raise FieldAdditionException(
                    field_name=new_field.name,
                    structure_name=self.name,
                )
            self._insert_field_at_index(new_field, field_index + 1)
        elif next_field_name is not None:
            field_index = self._get_field_index(next_field_name)
            if field_index is None:
                log_event_default(
                    NotAvailableFieldInStructure(
                        field_name=next_field_name,
                        structure_name=self.name,
                    )
                )
                raise FieldAdditionException(
                    field_name=new_field.name,
                    structure_name=self.name,
                )
            self._insert_field_at_index(new_field, field_index)
        else:
            self.fields[new_field.name] = new_field

    def _insert_field_at_index(self, new_field: Field, index: int) -> None:
        """Inserts a field at a specific index position."""
        field_items = list(self.fields.items())
        field_items.insert(index, (new_field.name, new_field))
        self.fields = dict(field_items)

    def _get_field_index(self, name: str) -> int | None:
        """Get the index of a field by name."""
        if name not in self.fields:
            return None
        return list(self.fields.keys()).index(name)

    def remove_field(self, name: str) -> None:
        """Removes the field with the provided name.

        Args:
            name: The field name to be removed.

        Raises:
            NotAvailableFieldException: If the field is not found.
        """
        if name not in self.fields:
            log_event_default(NotAvailableFieldInStructure(self.name, name))
            raise NotAvailableFieldException(structure_name=self.name, field_name=name)
        del self.fields[name]

    def remove_fields(self, names: list[str]) -> None:
        """Removes the fields with the provided names.

        Updates all the position values of the fields contained in this
        structure.

        Args:
            names: The list of fields to be removed.
        """
        for name in names:
            self.remove_field(name)

    def get_field_index(self, name: str) -> int:
        """Get the index of a field by name.

        Args:
            name: The field name to look for.

        Returns:
            The index of the field in the fields list.

        Raises:
            NotAvailableFieldException: If the field is not found.
        """
        index = self._get_field_index(name)
        if index is None:
            log_event_default(NotAvailableFieldInStructure(self.name, name))
            raise NotAvailableFieldException(structure_name=self.name, field_name=name)
        return index

    def get_number_of_fields(self) -> int:
        """Get the number of fields contained in the data structure.

        Counts both the structure's own fields and template-contributed
        fields, consistently with ``get_all_fields`` and ``get_field``.

        Returns:
            The number of fields.
        """
        return len(self.get_all_fields())

    # Field Characterisation related methods
    def _get_fields_associated_to_unique_structure_characterisation(
        self, characterisation: str
    ) -> list[Field]:
        if not self.has_characterisation(characterisation):
            return []
        structure_characterisation = self.get_characterisation(characterisation)
        if structure_characterisation is None:
            return []
        field_names = structure_characterisation.linked_fields
        return (
            self.get_fields_based_on_names(field_names)
            if field_names is not None
            else []
        )

    def has_primary_key(self) -> bool:
        return len(self.get_primary_key_fields()) > 0

    def get_primary_key_fields(self) -> list[Field]:
        """Get the list of fields contained in the primary key."""
        return self._get_fields_associated_to_unique_structure_characterisation(
            StructureCharacterisationDefinitionNames.PRIMARY_KEY
        )

    def has_tec_unique_key(self) -> bool:
        """Check if this structure has a technical key."""
        return len(self.get_tec_unique_key_fields()) > 0

    def get_tec_unique_key_fields(self) -> list[Field]:
        """Get the list of fields contained in the structure technical key."""
        return self._get_fields_associated_to_unique_structure_characterisation(
            StructureCharacterisationDefinitionNames.TECHNICAL_UNIQUE_KEY
        )

    def has_functional_unique_key(self) -> bool:
        """Check if this structure has a functional unique key."""
        return len(self.get_functional_unique_key_fields()) > 0

    def get_functional_unique_key_fields(self) -> list[Field]:
        """Get the list of fields contained in the structure functional key."""
        return self._get_fields_associated_to_unique_structure_characterisation(
            StructureCharacterisationDefinitionNames.FUNCTIONAL_UNIQUE_KEY
        )

    def get_last_update_tst_field(
        self,
        none_throws_exception: bool = False,
    ) -> Field | None:
        """Get the last update timestamp field if present.

        If there are multiple last update timestamp fields in this structure,
        a warning message is logged and one of the fields is returned.

        Args:
            none_throws_exception: When True, raises ValueError if no
                field with the characterisation is found.

        Raises:
            ValueError: If none_throws_exception is True and no field
                is found.
        """
        field = self.get_single_field_with_characterisation(
            FieldCharacterisationDefinitionNames.REC_LAST_UPDATE_TST
        )
        if field is None and none_throws_exception:
            raise ValueError(
                f"Structure '{self.name}' has no field with "
                f"'{FieldCharacterisationDefinitionNames.REC_LAST_UPDATE_TST}' "
                f"characterisation"
            )
        return field

    def get_insert_tst_field(self) -> Field | None:
        """
        Get the insert timestamp field if present.

        If there are multiple insert timestamp fields in this structure,
        a warning message is logged and one of the fields is returned.
        """
        return self.get_single_field_with_characterisation(
            FieldCharacterisationDefinitionNames.REC_INSERT_TST
        )

    def get_source_last_update_tst_field(self) -> Field | None:
        """
        Get the source last update timestamp field if present.

        If there are multiple source last update timestamp fields in this
        structure, a warning message is logged and one of the fields is
        returned.
        """
        return self.get_single_field_with_characterisation(
            FieldCharacterisationDefinitionNames.REC_SOURCE_LAST_UPDATE_TST
        )

    # Template-aware methods
    def get_all_fields(self) -> list[Field]:
        """Get all fields including those from referenced templates.

        Returns the structure's own fields merged with fields from all
        referenced templates following the relative_position ordering:
        START template fields, then structure fields, then END template
        fields. Structure fields override template fields with the same
        name. Among templates, earlier templates win over later ones.
        """
        start_fields: dict[str, Field] = {}
        end_fields: dict[str, Field] = {}
        for template in self.templates:
            for field_template in template.field_templates:
                field_instance = field_template.get_field_instance()
                target = (
                    start_fields
                    if field_template.relative_position
                    == FieldTemplateRelativePosition.START
                    else end_fields
                )
                if field_instance.name not in target:
                    target[field_instance.name] = field_instance

        seen: set[str] = set()
        result: list[Field] = []

        for field in start_fields.values():
            if field.name not in self.fields:
                seen.add(field.name)
                result.append(field)

        for field_name, field in self.fields.items():
            seen.add(field_name)
            result.append(field)

        for field in end_fields.values():
            if field.name not in seen:
                result.append(field)

        return result

    def get_direct_field_template_lineages(self) -> dict[str, FieldTemplateLineage]:
        """Get lineages of fields directly based on a field template.

        Keyed by the declared field name (not the template's embedded field
        name) so SQL rendering aliases each expression to the actual column
        even when the field was renamed through the fields dict key.
        """
        lineages: dict[str, FieldTemplateLineage] = {}
        for field in self.fields.values():
            if field.field_template is None:
                continue
            if field.field_template.lineage is None:
                continue
            lineages[field.name] = field.field_template.lineage
        return lineages

    def get_all_tags(self) -> list[str]:
        """Get all tags including those from referenced templates.

        Returns the union of structure tags and all template tags,
        deduplicated while preserving order.
        """
        all_tags: list[str] = []
        for template in self.templates:
            for tag in template.tags:
                if tag not in all_tags:
                    all_tags.append(tag)
        for tag in self.tags:
            if tag not in all_tags:
                all_tags.append(tag)
        return all_tags

    def get_deployable_characterisations(self) -> list[StructureCharacterisation]:
        """Get the structure characterisations that drive deployment DDL.

        A field-level ``unique`` characterisation expands into a
        single-column unique constraint named per the engine's
        default convention (``<table>_<column>_key``), so its DDL and
        the read-back constraint compare equal on every deploy.
        """
        deployable = list(self.characterisations)
        declared_unique_fields = {
            field_name
            for characterisation in self.characterisations
            for field_name in (characterisation.linked_fields or [])
            if characterisation.characterisation == "unique"
        }
        for field in self.get_all_fields():
            if not field.has_characterisation("unique"):
                continue
            if field.name in declared_unique_fields:
                continue
            deployable.append(
                StructureCharacterisation(
                    name=f"{self.name}_{field.name}_key",
                    characterisation="unique",
                    linked_fields=[field.name],
                ),
            )
        return deployable

    def get_all_pre_deployment_sql_hooks(self) -> list[str]:
        """Get pre-deployment SQL hooks, structure overriding templates."""
        if self.pre_deployment_sql_hook is not None:
            return self.pre_deployment_sql_hook
        for template in self.templates:
            if template.pre_deployment_sql_hook is not None:
                return template.pre_deployment_sql_hook
        return []

    def get_all_post_deployment_sql_hooks(self) -> list[str]:
        """Get post-deployment SQL hooks, structure overriding templates."""
        if self.post_deployment_sql_hook is not None:
            return self.post_deployment_sql_hook
        for template in self.templates:
            if template.post_deployment_sql_hook is not None:
                return template.post_deployment_sql_hook
        return []

    def get_all_properties(self) -> dict[str, str]:
        """Get all properties including those from referenced templates.

        Returns the merged properties from all templates and the
        structure's own properties. Structure properties have the highest
        priority, followed by earlier templates over later ones.
        """
        merged: dict[str, str] = {}
        for template in self.templates:
            if template.properties is not None:
                for key, value in template.properties.items():
                    if key not in merged:
                        merged[key] = value
        if self.properties is not None:
            merged.update(self.properties)
        return merged

    # Stats methods
    def get_stats(self) -> dict[str, str | int]:
        """Get the stats dictionary."""
        return self.stats if self.stats is not None else {}

    def get_stat(self, key: str) -> str | int | None:
        """Get a specific stat value."""
        return self.get_stats().get(key)

    # Properties methods
    def get_properties(self) -> dict[str, str]:
        """Get the properties dictionary."""
        return self.properties if self.properties is not None else {}

    def get_property(self, key: str) -> str | None:
        """Get a specific property value."""
        return self.get_properties().get(key)

    def has_property(self, key: str) -> bool:
        """Checks if this structure has the provided property key."""
        return key in self.get_properties()

    # Business metadata methods
    def get_business_metadata(self) -> dict[str, str]:
        """Get the business metadata dictionary."""
        return self.business_metadata if self.business_metadata is not None else {}

    def get_business_metadata_value(self, key: str) -> str | None:
        """Get a specific business metadata value."""
        return self.get_business_metadata().get(key)

    def has_business_metadata(self, key: str) -> bool:
        """Checks if this structure has the provided business metadata key."""
        return key in self.get_business_metadata()

    # Origin methods
    def get_origin(self) -> dict[str, Any]:
        """Get the origin dictionary."""
        return self.origin if self.origin is not None else {}

    def get_origin_value(self, key: str) -> Any:
        """Get a specific origin value."""
        return self.get_origin().get(key)

    # Options methods
    def get_options(self) -> dict[str, Any]:
        """Get the options dictionary."""
        return self.options if self.options is not None else {}

    def get_option_keys(self) -> list[str]:
        """Get the available option keys."""
        return list(self.get_options().keys())

    def has_option(self, key: str) -> bool:
        """Checks if this structure has the provided option key."""
        return key in self.get_option_keys()

    def get_option_value(self, key: str) -> Any:
        """Get the option value for the provided key."""
        return self.get_options().get(key)

    # Characterisation methods
    def get_characterisations(
        self,
    ) -> list[StructureCharacterisation]:
        return self.characterisations

    def get_characterisation_names(
        self,
    ) -> list[str]:
        return [char.characterisation for char in self.get_characterisations()]

    def get_characterisation(
        self, characterisation: str
    ) -> StructureCharacterisation | None:
        """Gets a structure characterisation by its characterisation value.

        Args:
            characterisation: The characterisation to look for.

        Returns:
            The StructureCharacterisation if found, None otherwise.
        """
        for char in self.get_characterisations():
            if char.characterisation == characterisation:
                return char
        return None

    def get_characterisations_by(
        self, characterisation: str
    ) -> list[StructureCharacterisation]:
        """Gets all structure characterisations matching the characterisation.

        Args:
            characterisation: The characterisation to look for.

        Returns:
            The list of matching StructureCharacterisation objects.
        """
        return [
            char
            for char in self.get_characterisations()
            if char.characterisation == characterisation
        ]

    def has_characterisations(self) -> bool:
        """Checks if this structure has any characterisations."""
        return len(self.get_characterisations()) > 0

    def has_characterisation(self, characterisation: str) -> bool:
        """Checks if structure has the provided characterisation."""
        return characterisation in self.get_characterisation_names()

    def has_any_characterisation(self, characterisations: list[str]) -> bool:
        """Checks if structure has any of the requested characterisations."""
        return any(
            char in self.get_characterisation_names() for char in characterisations
        )

    def get_matching_characterisations(self, characterisations: list[str]) -> list[str]:
        """Returns matching characterisations from the provided list.

        Args:
            characterisations: The list of characterisations to check.

        Returns:
            The list of characterisations that match.
        """
        return [char for char in characterisations if self.has_characterisation(char)]

    def add_characterisation(
        self, structure_characterisation: StructureCharacterisation
    ) -> None:
        """Adds the characterisation to the structure."""
        characterisation = structure_characterisation.characterisation
        name = structure_characterisation.name
        if self.has_characterisation(characterisation):
            if not cast(
                StructureCharacterisationDefinition,
                STRUCTURE_CHARACTERISATION_DEFINITIONS.get(characterisation),
            ).allowed_multiple_characterisations_per_structure:
                log_error_default(
                    f"Characterisation {characterisation} with name {name} "
                    f"is already present in structure {self.name}"
                )
                raise NldRuntimeException(
                    msg=f"Characterisation {characterisation} with name {name} "
                    f"is already present in structure {self.name}"
                )
        self.characterisations.append(structure_characterisation)

    def add_characterisation_with_name_only(
        self, characterisation: str, name: str
    ) -> None:
        """Adds characterisation to the characterisations of the structure.

        If characterisation already exists, an exception is thrown.

        Args:
            characterisation: The characterisation value.
            name: The characterisation instance name.
        """
        self.add_characterisation(
            StructureCharacterisation(characterisation=characterisation, name=name)
        )

    def remove_characterisation(self, characterisation: str) -> None:
        """Removes the characterisation from the structure.

        Args:
            characterisation: The characterisation to remove.
        """
        for char in self.characterisations:
            if char.characterisation == characterisation:
                self.characterisations.remove(char)
                break


class NamespacedStructure(NldNamespacedBaseModelWrapper[Structure]):
    """Structure wrapped with namespace information."""
