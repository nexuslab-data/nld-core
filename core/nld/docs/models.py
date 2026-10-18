import json
from datetime import datetime
from typing import Any

from pydantic import Field as PydanticField

from nld.pydantic import NldBaseModel

SNAPSHOT_SCHEMA_VERSION: str = "1.5"

STATE_SOURCE_API: str = "api"
STATE_SOURCE_FILE: str = "file"
STATE_SOURCE_NONE: str = "none"


class DocsSiteProject(NldBaseModel):
    """One project reachable from a generated site."""

    name: str
    title: str | None = None
    href: str
    structures: int = 0
    flows: int = 0


class DocsSiteConfig(NldBaseModel):
    """How a generated site reaches its data, written beside it.

    A site served by ``nld docs serve`` reads its state from the local API;
    a site published to a static host reads a ``state.json`` refreshed by a
    scheduled job, or shows no state at all. Keeping that in a file next to
    the page - rather than hard-coded in the script - is what lets the same
    build be served from a laptop, a bucket or an internal host.
    """

    schema_version: str = SNAPSHOT_SCHEMA_VERSION
    base_url: str = "."
    state_source: str = STATE_SOURCE_NONE
    state_url: str | None = None
    state_generated_at: datetime | None = None
    project_name: str | None = None
    projects: list[DocsSiteProject] = PydanticField(default_factory=list)


NODE_TYPE_FLOW: str = "flow"
NODE_TYPE_STRUCTURE: str = "structure"

ISSUE_KIND_BROKEN_REFERENCE: str = "broken_reference"
ISSUE_KIND_EXTERNAL_REFERENCE: str = "external_reference"
ISSUE_KIND_UNUSED_TEMPLATE: str = "unused_template"


class DocsSnapshotMeta(NldBaseModel):
    """What identifies one build of the snapshot, kept apart from its content.

    Everything outside ``meta`` is a pure function of the repository, so two
    builds of the same commit are byte-identical there and a CI diff can
    ignore this block alone.
    """

    generated_at: datetime
    generator_version: str | None = None
    environment: str | None = None


class DocsDocumentationBlock(NldBaseModel):
    """A markdown documentation block attached to an asset or a namespace."""

    title: str | None = None
    content: str = ""
    source_path: str | None = None


class DocsFieldSummary(NldBaseModel):
    """One field of a structure, flattened for display.

    The structure page shows the physical table, so template fields are
    listed with the declared ones: ``declared`` is False for a field a
    structure template contributes, and ``from_structure_template`` then
    names that template (``from_template`` names the field template).
    """

    name: str
    data_type: str = ""
    length: int = 0
    precision: int = 0
    default_value: Any = None
    description: str | None = None
    short_description: str | None = None
    characterisations: list[str] = PydanticField(default_factory=list)
    from_template: str | None = None
    from_structure_template: str | None = None
    declared: bool = True
    fields: list["DocsFieldSummary"] = PydanticField(default_factory=list)


class DocsCharacterisationSummary(NldBaseModel):
    """A structure-level characterisation (primary key, unique, index)."""

    characterisation: str
    name: str | None = None
    linked_fields: list[str] = PydanticField(default_factory=list)


class DocsOwnerSummary(NldBaseModel):
    """A resolved owner, with the namespace the declaration came from."""

    team: str
    contact: str | None = None
    source_namespace: str
    via: str | None = None


class DocsUsageReference(NldBaseModel):
    """One place a template or standard is used from.

    ``via`` names the indirection when the usage is not declared on the
    structure itself, e.g. a field template pulled in by a structure template.
    """

    structure_id: str
    field_name: str | None = None
    via: str | None = None


class DocsEntitySummary(NldBaseModel):
    """Any nld entity, rendered generically from its serialised payload.

    ``payload`` is the resolved model dump: it carries every attribute the
    entity type has today and every attribute it gains later, so the docs
    layer never has to be extended when an entity grows a field. The typed
    subclasses (structures, flows) leave it empty, since they already carry
    every attribute the UI renders.
    """

    entity_type: str
    entity_key: str
    name: str
    namespace: str
    node_id: str
    display_name: str
    category: str = ""
    description: str | None = None
    payload: dict[str, Any] = PydanticField(default_factory=dict)
    source_path: str | None = None
    source_text: str | None = None
    documentation: list[DocsDocumentationBlock] = PydanticField(default_factory=list)
    used_by: list[DocsUsageReference] = PydanticField(default_factory=list)


class DocsStructureSummary(DocsEntitySummary):
    """A structure with its fields, keys and lineage neighbours.

    ``audit_id`` points at the ``structure_audit`` entity profiling this
    structure, whose payload is carried once in ``entities``.
    """

    structure_type: str = ""
    connector_type: str | None = None
    short_name: str | None = None
    short_description: str | None = None
    tags: list[str] = PydanticField(default_factory=list)
    properties: dict[str, str] = PydanticField(default_factory=dict)
    business_metadata: dict[str, str] = PydanticField(default_factory=dict)
    templates: list[str] = PydanticField(default_factory=list)
    fields: list[DocsFieldSummary] = PydanticField(default_factory=list)
    characterisations: list[DocsCharacterisationSummary] = PydanticField(
        default_factory=list
    )
    primary_key_fields: list[str] = PydanticField(default_factory=list)
    produced_by: list[str] = PydanticField(default_factory=list)
    consumed_by: list[str] = PydanticField(default_factory=list)
    data_owners: list[DocsOwnerSummary] = PydanticField(default_factory=list)
    technical_owners: list[DocsOwnerSummary] = PydanticField(default_factory=list)
    model_links: list[dict[str, Any]] = PydanticField(default_factory=list)
    audit_id: str | None = None
    options: dict[str, Any] = PydanticField(default_factory=dict)
    pre_deployment_sql_hooks: list[str] = PydanticField(default_factory=list)
    post_deployment_sql_hooks: list[str] = PydanticField(default_factory=list)
    enforce_field_order: bool | None = None
    origin: dict[str, Any] | None = None
    stats: dict[str, str | int] | None = None


class DocsFlowPredecessorSummary(NldBaseModel):
    """A predecessor structure of a flow."""

    name: str
    full_path: str
    role: str | None = None
    key_field: str | None = None


class DocsResolvedPredecessor(NldBaseModel):
    """An upstream task the scheduling resolver settled on for one environment."""

    task_id: str
    flow_id: str | None = None
    external: bool = False


class DocsFlowScheduleSummary(NldBaseModel):
    """The scheduling of a flow in one environment.

    ``predecessors`` are the preconditions as declared on the trigger;
    ``resolved_predecessors`` are what the ``SchedulingResolver`` settles on
    once the automatic lineage and the additive / subtractive adjustments are
    applied, which is what the scheduler will actually wait for.
    """

    environment: str
    task_id: str | None = None
    enabled: bool = True
    trigger_kind: str | None = None
    cron: str | None = None
    predecessors: list[str] = PydanticField(default_factory=list)
    resolved_predecessors: list[DocsResolvedPredecessor] = PydanticField(
        default_factory=list
    )
    resolution_error: str | None = None
    frequency: dict[str, Any] | None = None
    params: dict[str, Any] = PydanticField(default_factory=dict)
    max_attempts: int | None = None
    max_attempts_origin: str | None = None


class DocsFlowSummary(DocsEntitySummary):
    """A data flow with its target, sources, strategy and scheduling.

    ``sql_text`` is what the SQL task will execute: the ``<flow>.sql`` file
    sitting next to the definition when there is one, otherwise the query
    rendered from the flow metadata (``sql_auto_rendered``). ``sql`` is the
    SQL configuration block (parameters, hooks, transformation).
    """

    task: str | None = None
    task_type: str | None = None
    target_structure: str | None = None
    write_strategy: str | None = None
    predecessors: list[DocsFlowPredecessorSummary] = PydanticField(default_factory=list)
    incremental: dict[str, Any] | None = None
    sql: dict[str, Any] | None = None
    sql_text: str | None = None
    sql_path: str | None = None
    sql_auto_rendered: bool = False
    sql_rendering_error: str | None = None
    quality_checks: dict[str, Any] | None = None
    params: list[dict[str, Any]] = PydanticField(default_factory=list)
    variables: list[dict[str, Any]] = PydanticField(default_factory=list)
    field_lineage: dict[str, Any] = PydanticField(default_factory=dict)
    schedules: list[DocsFlowScheduleSummary] = PydanticField(default_factory=list)
    owner: DocsOwnerSummary | None = None


class DocsTermTranslationSummary(NldBaseModel):
    """One translation of a business term."""

    language: str
    name: str
    plural: str | None = None
    synonyms: list[str] = PydanticField(default_factory=list)


class DocsTermSummary(NldBaseModel):
    """A business dictionary term, flattened for search and display."""

    name: str
    dictionary: str
    dictionary_node_id: str
    namespace: str
    language: str | None = None
    plural: str | None = None
    description: str | None = None
    synonyms: list[str] = PydanticField(default_factory=list)
    related_terms: list[str] = PydanticField(default_factory=list)
    translations: list[DocsTermTranslationSummary] = PydanticField(default_factory=list)


class DocsNamespaceSummary(NldBaseModel):
    """One namespace of the project and what it holds."""

    namespace: str
    entity_counts: dict[str, int] = PydanticField(default_factory=dict)
    documentation: list[DocsDocumentationBlock] = PydanticField(default_factory=list)


class DocsEntityTypeSummary(NldBaseModel):
    """One entity type of the registry, as the UI needs to present it."""

    name: str
    display_name: str
    category: str = ""
    folder_name: str = ""
    search_direction: str = ""
    count: int = 0


class DocsLineageNode(NldBaseModel):
    """A node of the lineage graph, with its computed layer.

    ``key`` is ``<node_type>:<node_id>``: a flow and the structure it writes
    may carry the same entity id, so the id alone cannot identify a node.
    ``missing`` marks a node a flow references but that no asset declares.
    ``external`` marks one declared by another project of the platform,
    which a single-project build cannot tell apart from a missing one -
    so it is only ever set when a catalog build says so.
    """

    key: str
    node_id: str
    node_type: str
    external: bool = False
    external_project: str | None = None
    label: str
    namespace: str | None = None
    layer: int = 0
    missing: bool = False


class DocsLineageEdge(NldBaseModel):
    """A directed edge of the lineage graph, between two node keys."""

    source: str
    target: str


class DocsLineage(NldBaseModel):
    """The whole flow dependency graph, laid out in layers."""

    nodes: list[DocsLineageNode] = PydanticField(default_factory=list)
    edges: list[DocsLineageEdge] = PydanticField(default_factory=list)


class DocsConnectionSummary(NldBaseModel):
    """A connection the project references, without any credential.

    Only connections the assets name are listed, so the snapshot describes
    the project and not the config folder of whoever built it. The type is
    filled in when the local configuration resolves the name.
    """

    name: str
    connector_type: str | None = None
    referenced_by: list[str] = PydanticField(default_factory=list)


class DocsProjectSummary(NldBaseModel):
    """The project identity and configuration, credentials excluded."""

    name: str
    version: str | None = None
    entity_path: str = "."
    default_environment: str | None = None
    environments: list[str] = PydanticField(default_factory=list)
    properties: dict[str, str] = PydanticField(default_factory=dict)
    variables: dict[str, str] = PydanticField(default_factory=dict)
    metadata_backend_connector: str | None = None
    connections: list[DocsConnectionSummary] = PydanticField(default_factory=list)
    documentation: list[DocsDocumentationBlock] = PydanticField(default_factory=list)


class DocsCoverage(NldBaseModel):
    """Documentation coverage over the documentable assets."""

    documented: int = 0
    total: int = 0
    missing: list[str] = PydanticField(default_factory=list)

    @property
    def ratio(self) -> float:
        """Share of documented assets, 0.0 when there is nothing to document."""
        if self.total == 0:
            return 0.0
        return self.documented / self.total


class DocsIssue(NldBaseModel):
    """One inconsistency found while reading the repository.

    ``broken_reference`` issues name an asset pointing at something that does
    not exist (a flow source, a model link side); ``external_reference``
    names one resolved by another project of the platform, which only a
    catalog build can tell apart; ``unused_template`` names a template no
    structure uses. Only ``broken_reference`` is an error.
    """

    kind: str
    asset: str
    message: str
    reference: str | None = None


class ProjectSnapshot(NldBaseModel):
    """The whole nld project as one serialisable document.

    Built from the repository content alone — no database is contacted — so
    it can be produced in CI, diffed between commits (ignoring ``meta``) and
    served offline.
    """

    schema_version: str = SNAPSHOT_SCHEMA_VERSION
    meta: DocsSnapshotMeta
    project: DocsProjectSummary
    namespaces: list[DocsNamespaceSummary] = PydanticField(default_factory=list)
    entity_types: list[DocsEntityTypeSummary] = PydanticField(default_factory=list)
    structures: list[DocsStructureSummary] = PydanticField(default_factory=list)
    flows: list[DocsFlowSummary] = PydanticField(default_factory=list)
    entities: dict[str, list[DocsEntitySummary]] = PydanticField(default_factory=dict)
    terms: list[DocsTermSummary] = PydanticField(default_factory=list)
    lineage: DocsLineage = PydanticField(default_factory=DocsLineage)
    counts: dict[str, int] = PydanticField(default_factory=dict)
    documentation_coverage: DocsCoverage = PydanticField(default_factory=DocsCoverage)
    issues: list[DocsIssue] = PydanticField(default_factory=list)

    @property
    def broken_references(self) -> list[DocsIssue]:
        """Return the issues that point at something missing."""
        return [
            issue for issue in self.issues if issue.kind == ISSUE_KIND_BROKEN_REFERENCE
        ]

    def content_json(self) -> str:
        """Serialise everything but ``meta``, for a build-to-build comparison."""
        return json.dumps(
            self.model_dump(
                mode="json",
                exclude={"meta"},
            ),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
