from typing import Any

from nld.flow.config import FlowNamespaceMapping
from nld.parameters.execution_params_def import (
    ExecutionParameterDefinition,
)
from nld.project.project import Project
from nld.pydantic import NldNamespace
from nld.scheduling.config import SchedulingNamespaceMapping
from nld.service.entity_definition import ENTITY_CATEGORY_DISPLAY_ORDER
from nld.structure.config import StructureNamespaceMapping
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

        self.execution_context.load_entities(
            namespace=self.namespace,
        )
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

        self._display_properties(project=project)
        self._display_folder_namespaces(project=project)
        self._display_deploy_groups(project=project)
        self._display_python_additional_paths(project=project)
        self._display_additional_entities(project=project)
        self._display_variables(project=project)
        self._display_environments(project=project)
        self.log_empty_line()
        self._display_flow_configuration(project=project)
        self.log_empty_line()
        self._display_namespace_configuration(project=project)

        self.log_separator_line()
        self.log_empty_line()

    def _display_properties(self, project: Project) -> None:
        """Display the free-form platform properties declared on the project."""
        properties = project.properties or {}
        self.log_info(f"  Properties: {len(properties)}")
        for key in sorted(properties):
            self.log_info(f"    - {key}: {properties[key]}")

    def _display_folder_namespaces(self, project: Project) -> None:
        """Display the namespaces whose entities are grouped in a folder."""
        folder_namespaces = project.folder_namespaces
        self.log_info(f"  Namespace folders: {len(folder_namespaces)}")
        for folder_namespace in sorted(folder_namespaces):
            self.log_info(f"    - {folder_namespace}")

    def _display_deploy_groups(self, project: Project) -> None:
        """Display the namespaces deployable on their own, and the deploy groups."""
        deploy_config = project.deploy_namespace_config
        deployable_namespaces = deploy_config.get_deployable_namespaces()
        self.log_info(f"  Deployable namespaces: {len(deployable_namespaces)}")
        for namespace in deployable_namespaces:
            self.log_info(f"    - {namespace}")
        deploy_groups = deploy_config.get_groups()
        self.log_info(f"  Deploy groups: {len(deploy_groups)}")
        for group, members in deploy_groups.items():
            self.log_info(f"    - {group}: {', '.join(members)}")

    def _display_environments(self, project: Project) -> None:
        """Display the declared environments and which one is the default."""
        environments = project.environments
        names = sorted(environments.get_environment_names())
        default = environments.default or "(not set)"
        self.log_info(f"  Environments: {len(names)} (default: {default})")
        for name in names:
            environment = environments.values[name]
            profile = environment.connection_profile or "(none)"
            self.log_info(
                f"    - {name}: connection profile {profile}, "
                f"{len(environment.variables)} variable(s)"
            )

    def _display_flow_configuration(self, project: Project) -> None:
        """Display the ``flow`` block — the project's flow-domain extension points."""
        flow_config = project.flow_config
        self.log_info("  Flow configuration:")

        task_types = flow_config.additional_flow_task_types
        self.log_info(f"    Additional flow task types: {len(task_types)}")
        for name in sorted(task_types):
            self.log_info(f"      - {name} (task_class={task_types[name]})")

        incremental_types = flow_config.additional_incremental_types
        self.log_info(f"    Additional incremental types: {len(incremental_types)}")
        for incremental_type in incremental_types:
            self.log_info(
                f"      - {incremental_type.name} "
                f"(logic={incremental_type.logic_module})"
            )

        quality_rules = flow_config.additional_quality_rules
        self.log_info(f"    Additional data quality rules: {len(quality_rules)}")
        for quality_rule in quality_rules:
            self.log_info(
                f"      - {quality_rule.name} (rule_class={quality_rule.rule_class})"
            )

    def _display_namespace_configuration(self, project: Project) -> None:
        """Display the ``namespaces`` block — the per-namespace declared facets.

        Keys are shown exactly as declared, wildcards included, since these are
        the declarations rather than the namespaces they end up resolving for.
        """
        structure_config = project.structure_namespace_config
        flow_config = project.flow_namespace_config
        scheduling_config = project.scheduling_namespace_config
        declared_namespaces = sorted(
            set(structure_config.get_namespaces())
            | set(flow_config.get_namespaces())
            | set(scheduling_config.get_namespaces())
        )

        self.log_info(f"  Namespace configuration: {len(declared_namespaces)}")
        for namespace in declared_namespaces:
            self.log_info(f"    - {namespace}")
            self._display_structure_facet(
                mapping=structure_config.mappings.get(namespace),
            )
            self._display_flow_facet(
                mapping=flow_config.mappings.get(namespace),
            )
            self._display_scheduling_facet(
                mapping=scheduling_config.mappings.get(namespace),
            )

    def _display_structure_facet(
        self,
        mapping: StructureNamespaceMapping | None,
    ) -> None:
        """Display one namespace's structure facet, when it declares one."""
        if mapping is None:
            return
        target = (
            f"{mapping.default_connection_name} / "
            f"{mapping.database_name} / {mapping.schema_name}"
        )
        tags = f" [tags: {', '.join(mapping.tags)}]" if mapping.tags else ""
        self.log_info(f"        structure : {target}{tags}")

    def _display_flow_facet(
        self,
        mapping: FlowNamespaceMapping | None,
    ) -> None:
        """Display one namespace's flow facet, when it declares one."""
        if mapping is None or mapping.default_state_backend_connector is None:
            return
        connector = mapping.default_state_backend_connector.primary.connector
        self.log_info(f"        flow      : default state backend {connector}")

    def _display_scheduling_facet(
        self,
        mapping: SchedulingNamespaceMapping | None,
    ) -> None:
        """Display one namespace's scheduling facet, when it declares one."""
        if mapping is None:
            return
        self.log_info(f"        scheduling: max attempts {mapping.max_attempts}")
        if mapping.alerting is not None:
            alerting = (
                f"on {', '.join(mapping.alerting.alert_on)} "
                f"through {', '.join(mapping.alerting.transports)}"
                if mapping.alerting.enabled
                else "disabled"
            )
            self.log_info(f"        scheduling: alerting {alerting}")

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

    def _display_variables(self, project: Project) -> None:
        """Display project-level variables defined in nld_project.yml."""
        variables = project.variables
        self.log_info(f"  Variables: {len(variables)}")
        for key in sorted(variables.keys()):
            self.log_info(f"    - {key}")

    def _display_namespaces(self, project: Project) -> None:
        """Display namespaces by first level, with their second levels inlined."""
        registry = project.entity_registry
        namespaces = registry.get_all_namespaces()
        grouped = self._group_namespaces_by_first_level(namespaces=namespaces)

        self.log_info("Namespaces:")
        self.log_separator_line()
        self.log_info(f"  Total: {len(namespaces)} in {len(grouped)} first level(s)")
        self.log_empty_line()

        if not grouped:
            self.log_info("  (none)")

        for first_level, second_levels in grouped.items():
            if second_levels:
                self.log_info(f"  - {first_level} ({', '.join(second_levels)})")
            else:
                self.log_info(f"  - {first_level}")

        self.log_separator_line()
        self.log_empty_line()

    @staticmethod
    def _group_namespaces_by_first_level(
        namespaces: list[str],
    ) -> dict[str, list[str]]:
        """Group namespaces by first level, collecting their second levels.

        A flat list of every namespace says little on a project with hundreds of
        them; grouping turns `apec.extraction`, `apec.ingestion`, `apec.raw` into
        the single line `apec (extraction, ingestion, raw)`. Levels below the
        second are folded into their second-level parent, and the root is left
        out entirely: it is the tree everything hangs from, not a first level.
        """
        grouped: dict[str, set[str]] = {}
        for namespace in namespaces:
            if namespace == NldNamespace.ROOT_VALUE:
                continue
            levels = namespace.split(".")
            second_levels = grouped.setdefault(levels[0], set())
            if len(levels) > 1:
                second_levels.add(levels[1])
        return {
            first_level: sorted(second_levels)
            for first_level, second_levels in sorted(grouped.items())
        }

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
