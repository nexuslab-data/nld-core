import datetime
import re
from importlib import metadata
from typing import Any

from nld.business import BusinessDictionary
from nld.docs.documentation import DocumentationCollector, relative_to_root
from nld.docs.lineage_builder import (
    build_lineage,
    build_lineage_key,
    collect_structure_neighbours,
)
from nld.docs.models import (
    ISSUE_KIND_BROKEN_REFERENCE,
    ISSUE_KIND_EXTERNAL_REFERENCE,
    ISSUE_KIND_UNUSED_TEMPLATE,
    NODE_TYPE_FLOW,
    NODE_TYPE_STRUCTURE,
    SNAPSHOT_SCHEMA_VERSION,
    DocsCharacterisationSummary,
    DocsConnectionSummary,
    DocsCoverage,
    DocsEntitySummary,
    DocsEntityTypeSummary,
    DocsFieldSummary,
    DocsFlowPredecessorSummary,
    DocsFlowScheduleSummary,
    DocsFlowSummary,
    DocsIssue,
    DocsNamespaceSummary,
    DocsOwnerSummary,
    DocsProjectSummary,
    DocsResolvedPredecessor,
    DocsSnapshotMeta,
    DocsStructureSummary,
    DocsTermSummary,
    DocsTermTranslationSummary,
    DocsUsageReference,
    ProjectSnapshot,
)
from nld.docs.source_index import EntitySourceIndex
from nld.flow.definition import DataFlowDefinition
from nld.flow.graph import DataFlowGraph
from nld.flow.sql import render_sql_from_flow_definition
from nld.flow.sql.sql_file_resolver import (
    load_sql_file_content,
    try_resolve_sql_file_path,
)
from nld.governance import (
    ResolvedOwner,
    resolve_flow_owner,
    resolve_structure_data_owners,
    resolve_structure_technical_owners,
)
from nld.pydantic import NldNamespace
from nld.scheduling import (
    NldSchedulingError,
    SchedulingGraph,
    SchedulingPolicy,
    SchedulingResolver,
)
from nld.service import EntityTypeNames
from nld.structure import Field, Structure
from nld.task.context import NldExecutionContext

DOCUMENTED_ENTITY_TYPES: tuple[str, ...] = (
    EntityTypeNames.STRUCTURE,
    EntityTypeNames.DATA_FLOW_DEFINITION,
)

GENERATOR_DISTRIBUTION_NAME: str = "nld-core"

SQL_TASK_TYPE: str = "sql"
SQL_TASK_CLASS_SUFFIX: str = "SQLFlowTask"


def _to_owner_summary(owner: ResolvedOwner) -> DocsOwnerSummary:
    """Convert a governance resolution result into its docs counterpart."""
    return DocsOwnerSummary(
        team=owner.team,
        contact=owner.contact,
        source_namespace=owner.source_namespace,
        via=owner.via,
    )


def _dump(model: Any) -> dict[str, Any]:
    """Serialise an nld model to a JSON-ready dict, dropping unset values."""
    dumped: dict[str, Any] = model.model_dump(
        mode="json",
        exclude_none=True,
    )
    return dumped


def _generator_version() -> str | None:
    """Return the installed nld-core version, None outside an installation."""
    try:
        return metadata.version(GENERATOR_DISTRIBUTION_NAME)
    except metadata.PackageNotFoundError:
        return None


def _strip_inline_markdown(text: str) -> str:
    """Reduce inline markdown to its plain text, for a one-line description."""
    plain = re.sub(r"\[([^\]]+)\]\((?:[^()]|\([^()]*\))*\)", r"\1", text)
    plain = re.sub(r"`([^`]*)`", r"\1", plain)
    plain = re.sub(r"\*\*([^*]+)\*\*", r"\1", plain)
    plain = re.sub(r"(^|[^*])\*([^*]+)\*", r"\1\2", plain)
    return plain


def _first_paragraph(text: str) -> str | None:
    """Return the first prose paragraph of a markdown text, headings skipped."""
    paragraph: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if not stripped:
            if paragraph:
                break
            continue
        if stripped.startswith(("#", "```", ">", "|")):
            continue
        paragraph.append(stripped)
    if not paragraph:
        return None
    return _strip_inline_markdown(text=" ".join(paragraph))


def _is_sql_flow(flow_definition: DataFlowDefinition) -> bool:
    """Whether the flow runs the SQL task, by type or by explicit class."""
    if flow_definition.task_type == SQL_TASK_TYPE:
        return True
    return (flow_definition.task or "").endswith(SQL_TASK_CLASS_SUFFIX)


def _build_field_summary(
    field: Field,
    from_template: str | None = None,
    from_structure_template: str | None = None,
    declared: bool = True,
) -> DocsFieldSummary:
    """Flatten a field and its sub-fields for display."""
    if from_template is None and field.field_template is not None:
        from_template = field.field_template.name
    return DocsFieldSummary(
        name=field.name,
        data_type=field.data_type,
        length=field.length,
        precision=field.precision,
        default_value=field.default_value,
        description=field.description,
        short_description=field.short_description,
        characterisations=[
            characterisation.characterisation
            for characterisation in field.characterisations
        ],
        from_template=from_template,
        from_structure_template=from_structure_template,
        declared=declared,
        fields=[
            _build_field_summary(field=sub_field) for sub_field in field.fields.values()
        ],
    )


def _build_structure_fields(structure: Structure) -> list[DocsFieldSummary]:
    """List the fields of the physical table: declared and template-provided.

    ``get_all_fields`` applies the template ordering (START templates, then
    the declared fields, then END templates) and the override rules; this
    only annotates where each resulting field came from.
    """
    template_origins: dict[str, tuple[str, str]] = {}
    for template in structure.templates:
        for field_template in template.field_templates:
            template_origins.setdefault(
                field_template.field.name,
                (field_template.name, template.name),
            )
    summaries: list[DocsFieldSummary] = []
    for field in structure.get_all_fields():
        declared = field.name in structure.fields
        origin = None if declared else template_origins.get(field.name)
        summaries.append(
            _build_field_summary(
                field=field,
                from_template=origin[0] if origin is not None else None,
                from_structure_template=origin[1] if origin is not None else None,
                declared=declared,
            )
        )
    return summaries


def _reference_exists(
    reference: str,
    namespace: str,
    known_ids: set[str],
) -> bool:
    """Whether an entity reference resolves, relative or fully qualified.

    A reference written inside a namespace may name a sibling by its bare
    name, so it resolves against the declaring namespace and then up its
    hierarchy, the way the registry resolves it - checking the fully
    qualified form alone reports every relative reference as broken.
    """
    if reference in known_ids:
        return True
    for level in reversed(NldNamespace(namespace).hierarchy):
        if level.is_root:
            continue
        if f"{level}.{reference}" in known_ids:
            return True
    return False


class ProjectSnapshotBuilder:
    """Builds the whole-project document the docs UI renders.

    The build reads the repository only: entities, templates, project
    configuration and the markdown that documents them. No connection is
    opened, so a snapshot can be produced in CI or on a laptop with no
    access to any environment.
    """

    def __init__(
        self,
        execution_context: NldExecutionContext,
        environment: str | None = None,
        external_structures: dict[str, str] | None = None,
    ) -> None:
        self.execution_context = execution_context
        self.environment = environment
        # Structure id -> the catalogued project that declares it. Only a
        # platform build can know this; a single project cannot tell a
        # reference produced upstream from one produced nowhere.
        self.external_structures = external_structures or {}
        self.registry = execution_context.entity_registry
        self.project = execution_context.project
        self.source_index = EntitySourceIndex()
        self.documentation_collector = DocumentationCollector(
            source_index=self.source_index,
            root_folder_path=self.project.root_folder_path,
        )
        self._graph: DataFlowGraph | None = None
        self._missing_documentation: list[str] = []
        self._documented_count = 0
        self._documentable_count = 0
        self._issues: list[DocsIssue] = []

    def build(self) -> ProjectSnapshot:
        """Build the snapshot from the loaded project."""
        self._index_sources()
        graph = self._get_graph()

        structures = self._build_structures(graph=graph)
        flows = self._build_flows(structures=structures)
        usages = self._collect_usages()
        entities = self._build_other_entities(usages=usages)
        namespaces = self._build_namespaces()
        terms = self._build_terms()
        self._collect_reference_issues(
            structures=structures,
            flows=flows,
            usages=usages,
        )

        counts: dict[str, int] = {
            EntityTypeNames.STRUCTURE: len(structures),
            EntityTypeNames.DATA_FLOW_DEFINITION: len(flows),
        }
        for entity_type, entity_list in entities.items():
            counts[entity_type] = len(entity_list)
        counts["namespace"] = len(namespaces)

        return ProjectSnapshot(
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            meta=DocsSnapshotMeta(
                generated_at=datetime.datetime.now(tz=datetime.UTC),
                generator_version=_generator_version(),
                environment=self.environment,
            ),
            project=self._build_project_summary(),
            namespaces=namespaces,
            entity_types=self._build_entity_types(counts=counts),
            structures=structures,
            flows=flows,
            entities=entities,
            terms=terms,
            lineage=build_lineage(
                external_owners=self.external_structures,
                graph=graph,
                existing_keys={
                    build_lineage_key(
                        node_type=NODE_TYPE_STRUCTURE,
                        entity_id=structure.node_id,
                    )
                    for structure in structures
                }
                | {
                    build_lineage_key(
                        node_type=NODE_TYPE_FLOW,
                        entity_id=flow.node_id,
                    )
                    for flow in flows
                },
            ),
            counts=counts,
            documentation_coverage=DocsCoverage(
                documented=self._documented_count,
                total=self._documentable_count,
                missing=sorted(self._missing_documentation),
            ),
            issues=sorted(
                self._issues,
                key=lambda issue: (issue.kind, issue.asset, issue.message),
            ),
        )

    def _index_sources(self) -> None:
        """Index every entity file of every root the project loads from."""
        root_directories = [
            self.project.entities_root_folder_path,
            *self.project.additional_entities_root_folder_paths,
        ]
        entity_layout = self.project.entity_layout
        for root_directory in root_directories:
            for entity_definition in self.registry.entity_definitions:
                self.source_index.index_entity_definition(
                    root_directory=root_directory,
                    entity_definition=entity_definition,
                    entity_layout=entity_layout,
                )
        self.documentation_collector.collect_namespace_documentation(
            root_directories=root_directories,
            entity_definitions=self.registry.entity_definitions,
            entity_layout=entity_layout,
        )

    def _get_graph(self) -> DataFlowGraph:
        """Build the flow dependency graph once and reuse it."""
        if self._graph is None:
            self._graph = DataFlowGraph(
                flow_dict=self.registry.get_data_flow_definition_dict(),
            )
        return self._graph

    def _build_project_summary(self) -> DocsProjectSummary:
        """Describe the project itself, credentials excluded."""
        return DocsProjectSummary(
            name=self.project.name,
            version=self.project.version,
            entity_path=self.project.entity_path,
            default_environment=self.project.environments.default,
            environments=sorted(self.project.environments.get_environment_names()),
            properties=self.project.properties or {},
            variables=self.project.variables,
            metadata_backend_connector=self.project.metadata_backend_connector,
            connections=self._collect_connections(),
            documentation=self.documentation_collector.project_documentation(),
        )

    def _collect_connections(self) -> list[DocsConnectionSummary]:
        """List the connections the assets reference, typed when configured.

        Reading the whole config folder would describe the builder's laptop,
        not the project: a snapshot built elsewhere would list other
        connections. Only names the project itself declares are kept.
        """
        references: dict[str, list[str]] = {}
        if self.project.metadata_backend_connector is not None:
            references.setdefault(self.project.metadata_backend_connector, []).append(
                "project metadata backend"
            )
        for namespaced in self.registry.get_data_flow_definition_dict().values():
            for name in sorted(namespaced.model.get_connector_connection_names()):
                references.setdefault(name, []).append(f"flow {namespaced.id}")
        structure_mappings = self.project.structure_namespace_config.mappings
        for namespace, mapping in sorted(structure_mappings.items()):
            references.setdefault(mapping.default_connection_name, []).append(
                f"structure namespace {namespace}"
            )

        configs = self.execution_context.connection_configs.configs
        return [
            DocsConnectionSummary(
                name=name,
                connector_type=(configs[name].type if name in configs else None),
                referenced_by=sorted(references[name]),
            )
            for name in sorted(references)
        ]

    def _build_entity_types(
        self,
        counts: dict[str, int],
    ) -> list[DocsEntityTypeSummary]:
        """List the registry's entity types with their asset counts."""
        return [
            DocsEntityTypeSummary(
                name=entity_definition.name,
                display_name=(entity_definition.display_name or entity_definition.name),
                category=entity_definition.category or "",
                folder_name=entity_definition.folder_name,
                search_direction=entity_definition.search_direction,
                count=counts.get(entity_definition.name, 0),
            )
            for entity_definition in self.registry.entity_definitions
        ]

    def _build_namespaces(self) -> list[DocsNamespaceSummary]:
        """List every namespace with the number of assets it holds."""
        all_entities = self.registry.get_all_entity_dict()
        counts_per_namespace: dict[str, dict[str, int]] = {}

        for entity_type, namespaced_entities in all_entities.items():
            for namespace, entity_dict in namespaced_entities.items():
                if not entity_dict:
                    continue
                namespace_key = str(namespace)
                counts_per_namespace.setdefault(namespace_key, {})[entity_type] = len(
                    entity_dict
                )

        for namespace_key in self.documentation_collector.documented_namespaces():
            counts_per_namespace.setdefault(namespace_key, {})

        return [
            DocsNamespaceSummary(
                namespace=namespace_key,
                entity_counts=counts_per_namespace[namespace_key],
                documentation=self.documentation_collector.namespace_documentation(
                    namespace=namespace_key,
                ),
            )
            for namespace_key in sorted(counts_per_namespace)
        ]

    def _register_documentation_coverage(
        self,
        node_id: str,
        documented: bool,
    ) -> None:
        """Count one documentable asset towards the coverage report."""
        self._documentable_count += 1
        if documented:
            self._documented_count += 1
        else:
            self._missing_documentation.append(node_id)

    def _build_structures(
        self,
        graph: DataFlowGraph,
    ) -> list[DocsStructureSummary]:
        """Build the structure pages, with fields, keys, owners and lineage."""
        structure_models = self._collect_structure_models()
        structure_audits = self._collect_structure_audits()

        summaries: list[DocsStructureSummary] = []
        for namespaced in self.registry.get_structure_dict().values():
            structure: Structure = namespaced.model
            namespace = str(namespaced.namespace)
            node_id = namespaced.id
            source_file = self.source_index.get(
                entity_type=EntityTypeNames.STRUCTURE,
                namespace=namespace,
                name=structure.name,
            )
            documentation = self.documentation_collector.entity_documentation(
                source_file=source_file,
            )
            self._register_documentation_coverage(
                node_id=f"structure:{node_id}",
                documented=bool(documentation) or bool(structure.description),
            )
            produced_by, consumed_by = collect_structure_neighbours(
                graph=graph,
                structure_id=node_id,
            )
            summaries.append(
                DocsStructureSummary(
                    entity_type=EntityTypeNames.STRUCTURE,
                    entity_key=structure.name,
                    name=structure.name,
                    namespace=namespace,
                    node_id=node_id,
                    display_name="Structure",
                    category=self._category_of(
                        entity_type=EntityTypeNames.STRUCTURE,
                    ),
                    description=structure.description,
                    source_path=self._relative_source_path(source_file=source_file),
                    source_text=source_file.text if source_file is not None else None,
                    documentation=documentation,
                    structure_type=structure.structure_type,
                    connector_type=structure.connector_type,
                    short_name=structure.short_name,
                    short_description=structure.short_description,
                    tags=structure.get_all_tags(),
                    properties=structure.get_all_properties(),
                    business_metadata=structure.business_metadata or {},
                    templates=[template.name for template in structure.templates],
                    fields=_build_structure_fields(structure=structure),
                    characterisations=[
                        DocsCharacterisationSummary(
                            characterisation=characterisation.characterisation,
                            name=characterisation.name,
                            linked_fields=characterisation.linked_fields or [],
                        )
                        for characterisation in structure.characterisations
                    ],
                    primary_key_fields=[
                        field.name for field in structure.get_primary_key_fields()
                    ],
                    produced_by=produced_by,
                    consumed_by=consumed_by,
                    data_owners=[
                        _to_owner_summary(owner=owner)
                        for owner in resolve_structure_data_owners(
                            registry=self.registry,
                            structure_id=node_id,
                            graph=graph,
                        )
                    ],
                    technical_owners=[
                        _to_owner_summary(owner=owner)
                        for owner in resolve_structure_technical_owners(
                            registry=self.registry,
                            structure_id=node_id,
                            graph=graph,
                        )
                    ],
                    model_links=structure_models.get(node_id, []),
                    audit_id=structure_audits.get(node_id),
                    options=structure.options or {},
                    pre_deployment_sql_hooks=structure.get_all_pre_deployment_sql_hooks(),
                    post_deployment_sql_hooks=(
                        structure.get_all_post_deployment_sql_hooks()
                    ),
                    enforce_field_order=structure.enforce_field_order,
                    origin=structure.origin,
                    stats=structure.stats,
                )
            )

        return sorted(summaries, key=lambda summary: summary.node_id)

    def _collect_structure_models(self) -> dict[str, list[dict[str, Any]]]:
        """Index the declared same-layer links, keyed by structure id.

        A link is attached to both of its sides, so a structure page lists
        every join it takes part in, whichever side declared it.
        """
        collected: dict[str, list[dict[str, Any]]] = {}
        for namespaced in self.registry.get_structure_model_dict().values():
            structure_model = namespaced.model
            for link_name, link in structure_model.links.items():
                link_payload: dict[str, Any] = {
                    "model": structure_model.name,
                    "namespace": str(namespaced.namespace),
                    "link": link_name,
                    **_dump(model=link),
                }
                for side_reference in (
                    str(link.left_structure),
                    str(link.right_structure),
                ):
                    collected.setdefault(side_reference, []).append(link_payload)
        return collected

    def _collect_structure_audits(self) -> dict[str, str]:
        """Map each audited structure to the id of the audit profiling it.

        The audit payload itself is carried once, on the ``structure_audit``
        entity; the structure only points at it.
        """
        collected: dict[str, str] = {}
        for namespaced in self.registry.get_structure_audit_dict().values():
            collected[str(namespaced.model.structure)] = namespaced.id
        return collected

    def _build_flows(
        self,
        structures: list[DocsStructureSummary],
    ) -> list[DocsFlowSummary]:
        """Build the flow pages, with sources, target, strategy and schedule."""
        schedules = self._collect_schedules()
        structure_by_id = {structure.node_id: structure for structure in structures}

        summaries: list[DocsFlowSummary] = []
        for namespaced in self.registry.get_data_flow_definition_dict().values():
            flow_definition = namespaced.model
            namespace = str(namespaced.namespace)
            node_id = namespaced.id
            source_file = self.source_index.get(
                entity_type=EntityTypeNames.DATA_FLOW_DEFINITION,
                namespace=namespace,
                name=flow_definition.name,
            )
            documentation = self.documentation_collector.entity_documentation(
                source_file=source_file,
            )
            self._register_documentation_coverage(
                node_id=f"flow:{node_id}",
                documented=bool(documentation),
            )
            payload = _dump(model=flow_definition)
            owner = resolve_flow_owner(
                registry=self.registry,
                flow_id=node_id,
            )
            target_structure = (
                str(flow_definition.target_structure)
                if flow_definition.target_structure is not None
                else None
            )
            sql_text, sql_path, auto_rendered, rendering_error = self._resolve_sql(
                flow_definition=flow_definition,
                namespace=namespace,
            )
            summaries.append(
                DocsFlowSummary(
                    entity_type=EntityTypeNames.DATA_FLOW_DEFINITION,
                    entity_key=flow_definition.name,
                    name=flow_definition.name,
                    namespace=namespace,
                    node_id=node_id,
                    display_name="Data Flow Definition",
                    category=self._category_of(
                        entity_type=EntityTypeNames.DATA_FLOW_DEFINITION,
                    ),
                    description=self._describe_flow(
                        documentation=documentation,
                        target=structure_by_id.get(target_structure or ""),
                    ),
                    source_path=self._relative_source_path(source_file=source_file),
                    source_text=source_file.text if source_file is not None else None,
                    documentation=documentation,
                    task=flow_definition.task,
                    task_type=flow_definition.task_type,
                    target_structure=target_structure,
                    write_strategy=flow_definition.write_strategy,
                    predecessors=[
                        DocsFlowPredecessorSummary(
                            name=predecessor_name,
                            full_path=str(predecessor.full_path),
                            role=predecessor.role,
                            key_field=predecessor.key_field,
                        )
                        for predecessor_name, predecessor in (
                            flow_definition.predecessors.items()
                        )
                    ],
                    incremental=payload.get("incremental"),
                    sql=payload.get("sql"),
                    sql_text=sql_text,
                    sql_path=sql_path,
                    sql_auto_rendered=auto_rendered,
                    sql_rendering_error=rendering_error,
                    quality_checks=payload.get("quality_checks"),
                    params=payload.get("params", []),
                    variables=payload.get("variables", []),
                    field_lineage=payload.get("target_from_sources_mapping", {}),
                    schedules=schedules.get(node_id, []),
                    owner=(
                        _to_owner_summary(owner=owner) if owner is not None else None
                    ),
                )
            )

        return sorted(summaries, key=lambda summary: summary.node_id)

    def _resolve_sql(
        self,
        flow_definition: DataFlowDefinition,
        namespace: str,
    ) -> tuple[str | None, str | None, bool, str | None]:
        """Return the SQL a flow executes: its file, or the auto-rendered query.

        Mirrors what the SQL task does at run time: the ``<flow>.sql`` next to
        the definition wins, and a flow with a ``target_from_sources_mapping``
        but no file is rendered from its metadata. A rendering failure is
        reported on the page rather than failing the build.
        """
        sql_file_path = try_resolve_sql_file_path(
            entities_root_folder_path=self.project.entities_root_folder_path,
            namespace=namespace,
            flow_name=flow_definition.name,
        )
        if sql_file_path is not None:
            relative_path = relative_to_root(
                path=sql_file_path,
                root_folder_path=self.project.root_folder_path,
            )
            try:
                return load_sql_file_content(sql_file_path), relative_path, False, None
            except (OSError, ValueError) as error:
                return None, relative_path, False, str(error)

        if not _is_sql_flow(flow_definition=flow_definition):
            return None, None, False, None
        if flow_definition.target_from_sources_mapping is None:
            return None, None, False, None

        try:
            return render_sql_from_flow_definition(flow_definition), None, True, None
        except Exception as error:  # noqa: BLE001 - the page reports the failure
            return None, None, True, f"{type(error).__name__}: {error}"

    @staticmethod
    def _describe_flow(
        documentation: list[Any],
        target: DocsStructureSummary | None,
    ) -> str | None:
        """Stand in for the description a flow does not declare.

        Flows carry no description attribute, so lists would show nothing:
        the first paragraph of the flow's documentation, then the target
        structure's description, fill that column.
        """
        for block in documentation:
            paragraph = _first_paragraph(text=block.content)
            if paragraph:
                return paragraph
        if target is not None:
            return target.short_description or target.description
        return None

    def _collect_schedules(self) -> dict[str, list[DocsFlowScheduleSummary]]:
        """Index the per-environment scheduling of every flow.

        Besides what the task declares, each environment carries the upstream
        tasks the ``SchedulingResolver`` settles on and the retry budget the
        ``SchedulingPolicy`` resolves, so the page shows what the scheduler
        will actually do rather than only what was written.
        """
        flow_task_dict = self.registry.get_flow_task_dict()
        policy = SchedulingPolicy(
            scheduling_namespace_config=self.project.scheduling_namespace_config,
        )
        task_flow_ids = {
            namespaced.id: str(namespaced.model.flow)
            for namespaced in flow_task_dict.values()
        }
        environment_names = sorted(
            {
                environment_name
                for namespaced in flow_task_dict.values()
                for environment_name in namespaced.model.environments
            }
        )
        graphs, resolution_errors = self._resolve_scheduling_graphs(
            environment_names=environment_names,
        )

        collected: dict[str, list[DocsFlowScheduleSummary]] = {}
        for namespaced in flow_task_dict.values():
            flow_task = namespaced.model
            flow_reference = str(flow_task.flow)
            resolved_attempts = policy.resolve_max_attempts(flow_task=namespaced)
            for environment_name, environment in sorted(flow_task.environments.items()):
                trigger_payload = (
                    _dump(model=environment.trigger)
                    if environment.trigger is not None
                    else {}
                )
                frequency = flow_task.resolved_frequency(environment_name)
                collected.setdefault(flow_reference, []).append(
                    DocsFlowScheduleSummary(
                        environment=environment_name,
                        task_id=namespaced.id,
                        enabled=environment.enabled,
                        trigger_kind=trigger_payload.get("kind"),
                        cron=trigger_payload.get("cron"),
                        predecessors=[
                            str(predecessor.get("name"))
                            for predecessor in trigger_payload.get("predecessors", [])
                        ],
                        resolved_predecessors=self._resolved_predecessors(
                            graph=graphs.get(environment_name),
                            task_id=namespaced.id,
                            task_flow_ids=task_flow_ids,
                        ),
                        resolution_error=resolution_errors.get(environment_name),
                        frequency=(
                            {"value": str(frequency)} if frequency is not None else None
                        ),
                        params=flow_task.merged_params(environment_name),
                        max_attempts=resolved_attempts.value,
                        max_attempts_origin=resolved_attempts.origin,
                    )
                )
        return collected

    def _resolve_scheduling_graphs(
        self,
        environment_names: list[str],
    ) -> tuple[dict[str, SchedulingGraph], dict[str, str]]:
        """Resolve the scheduling graph of every environment that declares one.

        A scheduling error in one environment is reported on that
        environment's rows instead of failing the whole build: the
        documentation of a broken project is exactly when a reader needs it.
        """
        graphs: dict[str, SchedulingGraph] = {}
        errors: dict[str, str] = {}
        for environment_name in environment_names:
            resolver = SchedulingResolver(
                environment=environment_name,
                registry=self.registry,
            )
            try:
                graphs[environment_name] = resolver.resolve()
            except NldSchedulingError as error:
                errors[environment_name] = str(error)
                self._issues.append(
                    DocsIssue(
                        kind=ISSUE_KIND_BROKEN_REFERENCE,
                        asset=f"scheduling:{environment_name}",
                        message=str(error),
                    )
                )
        return graphs, errors

    @staticmethod
    def _resolved_predecessors(
        graph: SchedulingGraph | None,
        task_id: str,
        task_flow_ids: dict[str, str],
    ) -> list[DocsResolvedPredecessor]:
        """Read the upstream tasks of one node out of a resolved graph."""
        if graph is None or not graph.has_node(task_id):
            return []
        nodes_by_id = {node["id"]: node for node in graph.serialize_nodes()}
        return [
            DocsResolvedPredecessor(
                task_id=upstream_id,
                flow_id=task_flow_ids.get(upstream_id),
                external=bool(nodes_by_id.get(upstream_id, {}).get("external", False)),
            )
            for upstream_id in graph.upstream_node_ids(task_id)
        ]

    def _build_terms(self) -> list[DocsTermSummary]:
        """Flatten every business dictionary term for search and display."""
        all_entities = self.registry.get_all_entity_dict()
        terms: list[DocsTermSummary] = []
        dictionaries = all_entities.get(EntityTypeNames.BUSINESS_DICTIONARY, {})
        for namespace, entity_dict in dictionaries.items():
            namespace_key = str(namespace)
            for model in entity_dict.values():
                if not isinstance(model, BusinessDictionary):
                    continue
                dictionary_node_id = self._build_node_id(
                    namespace=namespace_key,
                    name=model.name,
                )
                for term in model.terms.values():
                    terms.append(
                        DocsTermSummary(
                            name=term.name,
                            dictionary=model.name,
                            dictionary_node_id=dictionary_node_id,
                            namespace=namespace_key,
                            language=model.language,
                            plural=term.plural,
                            description=term.description,
                            synonyms=list(term.synonyms),
                            related_terms=list(term.related_terms),
                            translations=[
                                DocsTermTranslationSummary(
                                    language=translation.language,
                                    name=translation.name,
                                    plural=translation.plural,
                                    synonyms=list(translation.synonyms),
                                )
                                for translation in term.translations
                            ],
                        )
                    )
        return sorted(terms, key=lambda term: (term.dictionary_node_id, term.name))

    def _collect_usages(self) -> dict[str, dict[str, list[DocsUsageReference]]]:
        """Index which structures use each template and standard.

        Keyed by entity type then entity name, since templates and
        characterisation definitions are referenced by name and resolved
        through the namespace hierarchy.
        """
        usages: dict[str, dict[str, list[DocsUsageReference]]] = {}
        seen: set[tuple[str, str, str, str | None]] = set()

        def add(
            entity_type: str,
            entity_name: str,
            reference: DocsUsageReference,
        ) -> None:
            key = (
                entity_type,
                entity_name,
                reference.structure_id,
                reference.field_name,
            )
            if key in seen:
                return
            seen.add(key)
            usages.setdefault(entity_type, {}).setdefault(entity_name, []).append(
                reference
            )

        def add_field_usages(
            structure_id: str,
            fields: list[Field],
        ) -> None:
            for field in fields:
                if field.field_template is not None:
                    add(
                        EntityTypeNames.FIELD_TEMPLATE,
                        field.field_template.name,
                        DocsUsageReference(
                            structure_id=structure_id,
                            field_name=field.name,
                        ),
                    )
                for characterisation in field.characterisations:
                    add(
                        EntityTypeNames.FIELD_CHARACTERISATION_DEFINITION,
                        characterisation.characterisation,
                        DocsUsageReference(
                            structure_id=structure_id,
                            field_name=field.name,
                        ),
                    )
                add_field_usages(
                    structure_id=structure_id,
                    fields=list(field.fields.values()),
                )

        for namespaced in self.registry.get_structure_dict().values():
            structure: Structure = namespaced.model
            structure_id = namespaced.id
            add_field_usages(
                structure_id=structure_id,
                fields=structure.get_fields(),
            )
            for characterisation in structure.characterisations:
                add(
                    EntityTypeNames.FIELD_CHARACTERISATION_DEFINITION,
                    characterisation.characterisation,
                    DocsUsageReference(
                        structure_id=structure_id,
                        via="structure characterisation",
                    ),
                )
            for template in structure.templates:
                add(
                    EntityTypeNames.STRUCTURE_TEMPLATE,
                    template.name,
                    DocsUsageReference(structure_id=structure_id),
                )
                for field_template in template.field_templates:
                    add(
                        EntityTypeNames.FIELD_TEMPLATE,
                        field_template.name,
                        DocsUsageReference(
                            structure_id=structure_id,
                            field_name=field_template.field.name,
                            via=f"structure template {template.name}",
                        ),
                    )

        for by_name in usages.values():
            for references in by_name.values():
                references.sort(
                    key=lambda reference: (
                        reference.structure_id,
                        reference.field_name or "",
                    )
                )
        return usages

    def _build_other_entities(
        self,
        usages: dict[str, dict[str, list[DocsUsageReference]]],
    ) -> dict[str, list[DocsEntitySummary]]:
        """Build the generic pages of every entity type but structures and flows."""
        skipped = {
            EntityTypeNames.STRUCTURE,
            EntityTypeNames.DATA_FLOW_DEFINITION,
        }
        all_entities = self.registry.get_all_entity_dict()
        collected: dict[str, list[DocsEntitySummary]] = {}

        for entity_definition in self.registry.entity_definitions:
            entity_type = entity_definition.name
            if entity_type in skipped:
                continue
            usages_by_name = usages.get(entity_type, {})

            summaries: list[DocsEntitySummary] = []
            for namespace, entity_dict in all_entities.get(entity_type, {}).items():
                namespace_key = str(namespace)
                for entity_key, model in entity_dict.items():
                    name = getattr(model, "name", entity_key)
                    source_file = self.source_index.get(
                        entity_type=entity_type,
                        namespace=namespace_key,
                        name=name,
                    )
                    summaries.append(
                        DocsEntitySummary(
                            entity_type=entity_type,
                            entity_key=entity_key,
                            name=name,
                            namespace=namespace_key,
                            node_id=self._build_node_id(
                                namespace=namespace_key,
                                name=name,
                            ),
                            display_name=(
                                entity_definition.display_name or entity_type
                            ),
                            category=entity_definition.category or "",
                            description=self._describe(model=model),
                            payload=_dump(model=model),
                            source_path=self._relative_source_path(
                                source_file=source_file,
                            ),
                            source_text=(
                                source_file.text if source_file is not None else None
                            ),
                            documentation=(
                                self.documentation_collector.entity_documentation(
                                    source_file=source_file,
                                )
                            ),
                            used_by=usages_by_name.get(name, []),
                        )
                    )

            collected[entity_type] = sorted(
                summaries,
                key=lambda summary: summary.node_id,
            )

        return collected

    def _collect_reference_issues(
        self,
        structures: list[DocsStructureSummary],
        flows: list[DocsFlowSummary],
        usages: dict[str, dict[str, list[DocsUsageReference]]],
    ) -> None:
        """Record the cross-references that point at nothing.

        The registry loads assets without checking what they point at, so a
        renamed structure leaves flows and model links dangling until a run
        fails. ``nld docs check`` reports them from the repository alone.
        """
        structure_ids = {structure.node_id for structure in structures}

        def unresolved(
            asset: str,
            reference: str,
            message: str,
        ) -> None:
            """Record a reference this project cannot resolve on its own.

            Resolved by another catalogued project it is external and
            expected - a refined layer reading its acquisition layer is
            the normal shape of a platform. Resolved nowhere it is broken.

            A project built without a catalog has no way to know of the
            other projects, so every unresolved reference is broken there:
            a standalone project keeps its strict gate, and a platform one
            earns the distinction by naming its catalog.
            """
            owner = self.external_structures.get(reference)
            if owner is not None:
                self._issues.append(
                    DocsIssue(
                        kind=ISSUE_KIND_EXTERNAL_REFERENCE,
                        asset=asset,
                        message=f"{message}, declared by project '{owner}'",
                        reference=reference,
                    )
                )
                return
            self._issues.append(
                DocsIssue(
                    kind=ISSUE_KIND_BROKEN_REFERENCE,
                    asset=asset,
                    message=f"{message}, which does not exist",
                    reference=reference,
                )
            )

        for flow in flows:
            if flow.target_structure and not _reference_exists(
                reference=flow.target_structure,
                namespace=flow.namespace,
                known_ids=structure_ids,
            ):
                unresolved(
                    asset=f"flow:{flow.node_id}",
                    reference=flow.target_structure,
                    message=f"target structure '{flow.target_structure}'",
                )
            for predecessor in flow.predecessors:
                if not _reference_exists(
                    reference=predecessor.full_path,
                    namespace=flow.namespace,
                    known_ids=structure_ids,
                ):
                    unresolved(
                        asset=f"flow:{flow.node_id}",
                        reference=predecessor.full_path,
                        message=(
                            f"predecessor '{predecessor.name}' points at "
                            f"'{predecessor.full_path}'"
                        ),
                    )

        for namespaced in self.registry.get_structure_model_dict().values():
            model_id = namespaced.id
            for link_name, link in namespaced.model.links.items():
                for side_reference in (
                    str(link.left_structure),
                    str(link.right_structure),
                ):
                    if _reference_exists(
                        reference=side_reference,
                        namespace=str(namespaced.namespace),
                        known_ids=structure_ids,
                    ):
                        continue
                    unresolved(
                        asset=f"structure_model:{model_id}",
                        reference=side_reference,
                        message=(f"link '{link_name}' references '{side_reference}'"),
                    )

        template_accessors = (
            (EntityTypeNames.FIELD_TEMPLATE, self.registry.get_field_template_dict),
            (
                EntityTypeNames.STRUCTURE_TEMPLATE,
                self.registry.get_structure_template_dict,
            ),
        )
        for entity_type, accessor in template_accessors:
            used_names = set(usages.get(entity_type, {}))
            for namespaced_template in accessor().values():
                if namespaced_template.model.name in used_names:
                    continue
                self._issues.append(
                    DocsIssue(
                        kind=ISSUE_KIND_UNUSED_TEMPLATE,
                        asset=f"{entity_type}:{namespaced_template.id}",
                        message="no structure uses this template",
                    )
                )

    @staticmethod
    def _build_node_id(
        namespace: str,
        name: str,
    ) -> str:
        """Build the ``namespace.name`` identifier used across the UI."""
        if NldNamespace(namespace).is_root:
            return name
        return f"{namespace}.{name}"

    @staticmethod
    def _describe(model: Any) -> str | None:
        """Return an entity's own description when it declares one."""
        description = getattr(model, "description", None)
        if isinstance(description, str):
            return description
        if isinstance(model, BusinessDictionary):
            return f"{len(model.terms)} term(s)"
        return None

    def _category_of(
        self,
        entity_type: str,
    ) -> str:
        """Return the registry category of an entity type."""
        entity_definition = self.registry.get_entity_definition(
            entity_name=entity_type,
        )
        if entity_definition is None:
            return ""
        return entity_definition.category or ""

    def _relative_source_path(
        self,
        source_file: Any,
    ) -> str | None:
        """Return the source path relative to the project root."""
        if source_file is None:
            return None
        return self.source_index.relative_path(
            source_file=source_file,
            root_directory=self.project.root_folder_path,
        )
