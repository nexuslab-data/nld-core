from typing import Any

from nld.parameters.execution_params_def import (
    ExecutionParameterDefinition,
)
from nld.project.project import Project
from nld.service.entity_definition import ENTITY_CATEGORY_DISPLAY_ORDER
from nld.task import BaseRunStatus, StandardTask


class ProjectInfoTask(StandardTask):
    """Displays comprehensive information about the project and entity counts."""

    init_params = [
        ExecutionParameterDefinition(name="namespace", mandatory=False),
    ]

    def __init__(
        self,
        namespace: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.namespace = namespace

    def run(self, **kwargs: Any) -> bool:
        """Display project information and all entity counts."""
        run_status = BaseRunStatus.SUCCESS.value

        self.execution_context.load_entities()
        project = self.execution_context.project

        self._display_project_info(project=project)
        self._display_configuration(project=project)
        self._display_namespaces(project=project)
        self._display_entity_counts(project=project)

        return run_status

    def _display_project_info(self, project: Project) -> None:
        """Display basic project information."""
        title_lines = [f"Project: {project.name}"]
        if project.version:
            title_lines.append(f"Version: {project.version}")
        title_lines.append(f"Root Path: {project.root_folder_path}")
        title_lines.append(f"Entities Path: {project.entities_root_folder_path}")
        self.log_section_header(*title_lines)
        self.log_empty_line()

    def _display_configuration(self, project: Project) -> None:
        """Display project-level configuration declared in nld_project.yml."""
        self.log_info("Configuration:")
        self.log_separator_line()

        metadata_backend = project.metadata_backend_connector or "(not set)"
        self.log_info(f"  Metadata backend connector: {metadata_backend}")

        self._display_python_additional_paths(project=project)
        self._display_additional_entities(project=project)
        self._display_additional_incremental_types(project=project)
        self._display_variables(project=project)

        self.log_separator_line()
        self.log_empty_line()

    def _display_python_additional_paths(self, project: Project) -> None:
        """Display configured python additional paths grouped by key."""
        paths = project.python_additional_paths
        self.log_info("  Python additional paths:")
        if not paths:
            self.log_info("    (none)")
            return
        for key in sorted(paths.keys()):
            entries = paths[key]
            if not entries:
                self.log_info(f"    - {key}: (none)")
                continue
            self.log_info(f"    - {key}:")
            for entry in entries:
                self.log_info(f"        * {entry}")

    def _display_additional_entities(self, project: Project) -> None:
        """Display additional entity definitions declared in the project."""
        entries = project.additional_entities
        self.log_info(f"  Additional entities: {len(entries)}")
        for entry in entries:
            self.log_info(f"    - {entry.name}")

    def _display_additional_incremental_types(self, project: Project) -> None:
        """Display additional incremental types declared in the project."""
        entries = project.additional_incremental_types
        self.log_info(f"  Additional incremental types: {len(entries)}")
        for entry in entries:
            self.log_info(f"    - {entry.name} (logic={entry.logic_module})")

    def _display_variables(self, project: Project) -> None:
        """Display project-level variables defined in nld_project.yml."""
        variables = project.variables
        self.log_info(f"  Variables: {len(variables)}")
        for key in sorted(variables.keys()):
            self.log_info(f"    - {key}")

    def _display_namespaces(self, project: Project) -> None:
        """Display the list of namespaces in the registry."""
        registry = project.entity_registry
        namespaces = registry.get_all_namespaces()

        self.log_info("Namespaces:")
        self.log_separator_line()
        self.log_info(f"  Total: {len(namespaces)}")
        self.log_empty_line()

        for namespace in sorted(namespaces):
            self.log_info(f"  - {namespace}")

        self.log_separator_line()
        self.log_empty_line()

    def _display_entity_counts(self, project: Project) -> None:
        """Display counts for all entity types in the registry, grouped by category."""
        registry = project.entity_registry

        self.log_info("Entity Counts:")
        if self.namespace:
            self.log_info(f"Namespace: {self.namespace}")
        self.log_separator_line()

        grouped = registry.get_entity_definitions_grouped_by_category()
        sorted_categories = self._sort_categories(categories=list(grouped.keys()))

        total_entities = 0

        for category in sorted_categories:
            entity_definitions = grouped[category]

            self.log_empty_line()
            category_label = category if category else "Other Entities"
            self.log_info(f"{category_label}:")

            for entity_def in entity_definitions:
                count = len(
                    registry.list_entity_keys(
                        entity_type=entity_def.name,
                        namespace=self.namespace,
                    )
                )
                total_entities += count
                label = (
                    entity_def.display_name
                    if entity_def.display_name
                    else entity_def.name
                )
                self._display_count(
                    label=label,
                    count=count,
                )

        self.log_empty_line()
        self.log_separator_line()
        self.log_info(f"Total Entities: {total_entities}")
        self.log_separator_line()

    def _sort_categories(
        self,
        categories: list[str | None],
    ) -> list[str | None]:
        """
        Sort categories by their display order.

        Categories with defined order come first, followed by categories without
        defined order, followed by None at the end.
        """

        def sort_key(category: str | None) -> tuple[int, int, str]:
            if category is None:
                return (2, 0, "")
            order = ENTITY_CATEGORY_DISPLAY_ORDER.get(category)
            if order is not None:
                return (0, order, category)
            return (1, 0, category)

        return sorted(categories, key=sort_key)

    def _display_count(self, label: str, count: int) -> None:
        """Display formatted count for an entity type."""
        self.log_info(f"  {label:<35} : {count:>5}")
