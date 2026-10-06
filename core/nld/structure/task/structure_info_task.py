from typing import Any, ClassVar

from nld.parameters import (
    ExecutionParameterDefinition,
)
from nld.service import EntityTypeNames
from nld.structure.field.field_data_type import FieldDataType
from nld.task.base import StandardTask


class StructureInfoTask(StandardTask):
    """
    Task responsible for displaying general information about an NLD
    structure definition.

    This task loads a project, retrieves the structure from the entity
    registry, and returns detailed information about the structure
    including fields, characterisations, properties, tags, and templates.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        "name",
        ExecutionParameterDefinition(
            name="namespace",
            mandatory=False,
        ),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        name: str,
        namespace: str | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the StructureInfoTask.

        Args:
            name: Name of the structure to display information about
            namespace: Optional namespace for the structure
            **kwargs: Additional arguments (e.g., exec_uuid)
        """
        super().__init__(**kwargs)

        self.execution_context.load_entities(
            entity_types=[EntityTypeNames.STRUCTURE],
            namespace=namespace,
        )

        namespaced_structure = self.execution_context.entity_registry.get_structure(
            entity_key=name,
            namespace=namespace,
        )
        self.structure_namespace = namespaced_structure.namespace
        self.structure = namespaced_structure.model

    def run(self, **kwargs: Any) -> bool:
        """Display general information about the structure."""
        self._display_header()
        self._display_properties()
        self._display_templates()
        self._display_fields()
        self._display_characterisations()
        self._display_tags()

        return True

    def _display_header(self) -> None:
        """Display structure header information."""
        title_lines = [f"Structure: {self.structure.name}"]
        if self.structure_namespace:
            title_lines.append(f"Namespace: {self.structure_namespace}")
        title_lines.append(f"Type: {self.structure.structure_type}")
        if self.structure.connector_type:
            title_lines.append(f"Connector Type: {self.structure.connector_type}")
        if self.structure.description:
            title_lines.append(f"Description: {self.structure.description}")
        self.log_section_header(*title_lines)
        self.log_empty_line()

    def _display_properties(self) -> None:
        """Display structure properties including template-contributed ones."""
        all_properties = self.structure.get_all_properties()

        self.log_info("Properties:")
        self.log_separator_line()

        if not all_properties:
            self.log_info("  No properties defined")
        else:
            self.log_empty_line()
            template_property_keys = self._get_template_property_keys()
            for key, value in all_properties.items():
                template_name = template_property_keys.get(key, "")
                template_col = f" | Template: {template_name}" if template_name else ""
                self.log_info(f"  {key:<28} : {value}{template_col}")
            self.log_empty_line()

        self.log_separator_line()
        self.log_empty_line()

    def _display_fields(self) -> None:
        """Display structure fields including template-contributed ones."""
        all_fields = self.structure.get_all_fields()

        self.log_info("Fields:")
        self.log_separator_line()

        if not all_fields:
            self.log_info("  No fields defined")
        else:
            self.log_empty_line()
            template_field_map = self._get_template_field_map()

            headers = (
                "Name",
                "Data Type",
                "Characterisations",
                "Template",
            )
            rows: list[tuple[str, ...]] = []
            for field in all_fields:
                field_data_type = FieldDataType(
                    data_type=field.data_type,
                    length=field.length,
                    precision=field.precision,
                )
                rows.append(
                    (
                        field.name,
                        str(field_data_type),
                        ", ".join(field.get_characterisation_names()),
                        template_field_map.get(field.name, ""),
                    )
                )

            self.log_aligned_table(
                headers=list(headers),
                rows=[list(row) for row in rows],
            )
            self.log_empty_line()

        self.log_separator_line()
        self.log_empty_line()

    def _display_characterisations(self) -> None:
        """Display structure-level characterisations."""
        self.log_info("Characterisations:")
        self.log_separator_line()

        if not self.structure.characterisations:
            self.log_info("  No characterisations defined")
        else:
            self.log_empty_line()
            for char in self.structure.characterisations:
                linked = ", ".join(char.linked_fields) if char.linked_fields else "None"
                self.log_info(
                    f"  {char.name:<20} | Type: {char.characterisation:<16} | "
                    f"Fields: {linked}"
                )
            self.log_empty_line()

        self.log_separator_line()
        self.log_empty_line()

    def _display_tags(self) -> None:
        """Display structure tags including template-contributed ones."""
        all_tags = self.structure.get_all_tags()

        self.log_info("Tags:")
        self.log_separator_line()

        if not all_tags:
            self.log_info("  No tags defined")
        else:
            self.log_empty_line()
            template_tags = self._get_template_tags()
            for tag in all_tags:
                template_name = template_tags.get(tag, "")
                suffix = f"  (from: {template_name})" if template_name else ""
                self.log_info(f"  - {tag}{suffix}")
            self.log_empty_line()

        self.log_separator_line()
        self.log_empty_line()

    def _display_templates(self) -> None:
        """Display structure templates."""
        self.log_info("Templates:")
        self.log_separator_line()

        if not self.structure.templates:
            self.log_info("  No templates defined")
        else:
            self.log_empty_line()
            for template in self.structure.templates:
                self.log_info(f"  - {template.name}")
            self.log_empty_line()

        self.log_separator_line()
        self.log_empty_line()

    def _get_template_field_map(self) -> dict[str, str]:
        """Build a mapping of field name to template name.

        Structure-template fields show the structure template name and
        fields directly based on a field template show the field template
        name. Fields declared without any template get an empty string.
        """
        field_map: dict[str, str] = {}
        for template in self.structure.templates:
            for field_template in template.field_templates:
                field_instance = field_template.get_field_instance()
                if field_instance.name not in field_map:
                    field_map[field_instance.name] = template.name
        for field_name, field in self.structure.fields.items():
            field_map[field_name] = (
                field.field_template.name if field.field_template is not None else ""
            )
        return field_map

    def _get_template_property_keys(self) -> dict[str, str]:
        """Build a mapping of property key to template name."""
        property_map: dict[str, str] = {}
        for template in self.structure.templates:
            if template.properties is not None:
                for key in template.properties:
                    if key not in property_map:
                        property_map[key] = template.name
        if self.structure.properties is not None:
            for key in self.structure.properties:
                property_map[key] = ""
        return property_map

    def _get_template_tags(self) -> dict[str, str]:
        """Build a mapping of tag to template name for template-contributed tags."""
        tag_map: dict[str, str] = {}
        for template in self.structure.templates:
            for tag in template.tags:
                if tag not in tag_map:
                    tag_map[tag] = template.name
        for tag in self.structure.tags:
            tag_map[tag] = ""
        return tag_map
