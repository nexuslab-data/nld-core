import os
from typing import Any

from pydantic import Field, field_validator

from nld.flow.alerting import (
    FlowAlertTransportManifest,
    get_flow_alert_transport_registry,
)
from nld.flow.config import (
    FlowNamespaceConfig,
    FlowNamespaceMapping,
    FlowProjectConfig,
)
from nld.flow.incremental.models import FlowIncrementalTypeManifest
from nld.flow.incremental.services.registry import (
    get_flow_incremental_type_registry,
)
from nld.flow.quality.models import DataQualityRuleManifest
from nld.flow.quality.registry import get_data_quality_rule_registry
from nld.pydantic import (
    SEEDS_FOLDER_NAME,
    WILDCARD_CHARACTER,
    NldBaseModel,
    NldEntityLayout,
    NldNamespace,
)
from nld.scheduling.config import (
    SchedulingNamespaceConfig,
    SchedulingNamespaceMapping,
)
from nld.service.nld_entity_registry import ALL_ENTITY_DEFINITIONS, NldEntityRegistry
from nld.structure.config import (
    StructureNamespaceConfig,
    StructureNamespaceMapping,
)
from nld.utils.yaml_util import load_yaml_file_into_dict

from .additional_entity_config import AdditionalEntityConfig
from .additional_entity_paths import resolve_additional_entity_paths
from .deploy_config import DeployNamespaceConfig, DeployNamespaceMapping
from .environment_config import EnvironmentsConfig
from .project_exceptions import (
    NldMissingProjectYamlFile,
    NldProjectError,
)

NLD_PROJECT_FILENAME = "nld_project.yml"
# TODO: transitional — delete both constants and ``_reject_legacy_config_files``
# once every project has migrated (all lakehouses were migrated with 0.1.2a3).
# They exist only to turn a forgotten legacy file into an explicit error instead
# of a silent no-op; the hard reject is not meant to stay in the codebase.
LEGACY_FLOW_CONFIG_FILENAME = "config/flow.yaml"
LEGACY_STRUCTURE_CONFIG_FILENAME = "config/structure.yaml"
KNOWN_PYTHON_ADDITIONAL_PATHS_KEYS = {"flows", "sql_transformations"}
NAMESPACE_FACET_DEPLOY = "deploy"
NAMESPACE_FACET_FLOW = "flow"
NAMESPACE_FACET_FOLDER = "folder"
NAMESPACE_FACET_SCHEDULING = "scheduling"
NAMESPACE_FACET_STRUCTURE = "structure"
KNOWN_NAMESPACE_FACETS = {
    NAMESPACE_FACET_DEPLOY,
    NAMESPACE_FACET_FLOW,
    NAMESPACE_FACET_FOLDER,
    NAMESPACE_FACET_SCHEDULING,
    NAMESPACE_FACET_STRUCTURE,
}


def load_project_to_dict(root_path: str) -> dict[str, Any]:
    root_path = os.path.normpath(root_path)
    project_filepath = os.path.join(root_path, NLD_PROJECT_FILENAME)

    if not os.path.exists(project_filepath):
        raise NldMissingProjectYamlFile(path=project_filepath)

    project_dict = load_yaml_file_into_dict(project_filepath)

    if not isinstance(project_dict, dict):
        raise NldProjectError(f"{NLD_PROJECT_FILENAME} does not parse to a dictionary")

    return project_dict


def _reject_legacy_config_files(root_path: str) -> None:
    """Fail when the pre-0.1.2a3 ``config/`` files are still present.

    Their content moved into the ``namespaces`` block of ``nld_project.yml``.
    Leaving them on disk would be silently ignored, so refuse to load instead:
    a missing structure mapping surfaces as a confusing "namespace not found"
    much later, and a missing flow mapping silently drops the namespace's
    default state backend connector.

    TODO: transitional — remove this hard reject in the near future, once no
    project can still be carrying the legacy files.
    """
    for filename in (
        LEGACY_STRUCTURE_CONFIG_FILENAME,
        LEGACY_FLOW_CONFIG_FILENAME,
    ):
        if not os.path.exists(os.path.join(root_path, filename)):
            continue
        facet = os.path.basename(filename).removesuffix(".yaml")
        raise NldProjectError(
            f"'{filename}' is no longer read. Move its mappings into the "
            f"'namespaces' block of {NLD_PROJECT_FILENAME}, one '{facet}' entry "
            f"per namespace, then delete the file. For example:\n"
            f"namespaces:\n"
            f"  .:\n"
            f"    {facet}:\n"
            f"      <the settings previously under mappings['.']>"
        )


def _load_namespace_configs(
    namespaces: dict[str, Any],
) -> tuple[
    StructureNamespaceConfig,
    FlowNamespaceConfig,
    SchedulingNamespaceConfig,
    list[str],
    DeployNamespaceConfig,
]:
    """Split the ``namespaces`` block into one config per facet.

    The project file is namespace-first (each namespace declaring its structure,
    flow and scheduling settings together); the runtime wants one namespace-keyed
    config per facet, so the block is transposed here. The ``folder`` facet is
    not a mapping: it flags the namespaces stored as namespace folders, which
    are returned as a list.
    """
    deploy_mappings: dict[str, DeployNamespaceMapping] = {}
    flow_mappings: dict[str, FlowNamespaceMapping] = {}
    folder_namespaces: list[str] = []
    scheduling_mappings: dict[str, SchedulingNamespaceMapping] = {}
    structure_mappings: dict[str, StructureNamespaceMapping] = {}

    for namespace, facets in namespaces.items():
        if not isinstance(facets, dict):
            raise NldProjectError(
                f"Namespace '{namespace}' must map to a dictionary of facets "
                f"({sorted(KNOWN_NAMESPACE_FACETS)}), got {type(facets).__name__}"
            )

        unknown_facets = set(facets) - KNOWN_NAMESPACE_FACETS
        if unknown_facets:
            raise NldProjectError(
                f"Unknown facets {sorted(unknown_facets)} declared for namespace "
                f"'{namespace}'. Known facets are: "
                f"{sorted(KNOWN_NAMESPACE_FACETS)}"
            )

        if NAMESPACE_FACET_STRUCTURE in facets:
            structure_mappings[namespace] = StructureNamespaceMapping.model_validate(
                facets[NAMESPACE_FACET_STRUCTURE],
            )
        if NAMESPACE_FACET_FLOW in facets:
            flow_mappings[namespace] = FlowNamespaceMapping.model_validate(
                facets[NAMESPACE_FACET_FLOW],
            )
        if NAMESPACE_FACET_SCHEDULING in facets:
            scheduling_mappings[namespace] = SchedulingNamespaceMapping.model_validate(
                facets[NAMESPACE_FACET_SCHEDULING],
            )
        if _is_namespace_folder(
            namespace=namespace,
            facets=facets,
        ):
            folder_namespaces.append(namespace)
        if NAMESPACE_FACET_DEPLOY in facets:
            deploy_mappings[namespace] = _load_deploy_mapping(
                namespace=namespace,
                deploy_facet=facets[NAMESPACE_FACET_DEPLOY],
            )

    deploy_namespace_config = DeployNamespaceConfig(mappings=deploy_mappings)
    _validate_deploy_groups(deploy_namespace_config=deploy_namespace_config)
    return (
        StructureNamespaceConfig(mappings=structure_mappings),
        FlowNamespaceConfig(mappings=flow_mappings),
        SchedulingNamespaceConfig(mappings=scheduling_mappings),
        folder_namespaces,
        deploy_namespace_config,
    )


def _is_namespace_folder(namespace: str, facets: dict[str, Any]) -> bool:
    """Read the ``folder`` facet of a namespace, rejecting invalid ones.

    A folder is a concrete location on disk, so the facet cannot apply to a
    wildcard key (it would match an open set of namespaces) nor to the root
    namespace (whose entities already sit at the top of the entity path).
    """
    folder = facets.get(NAMESPACE_FACET_FOLDER, False)
    if not isinstance(folder, bool):
        raise NldProjectError(
            f"The '{NAMESPACE_FACET_FOLDER}' facet of namespace '{namespace}' "
            f"must be true or false, got {folder!r}"
        )
    if not folder:
        return False
    if WILDCARD_CHARACTER in namespace:
        raise NldProjectError(
            f"Namespace '{namespace}' is a wildcard pattern and cannot be "
            f"declared as a namespace folder ('{NAMESPACE_FACET_FOLDER}: true')"
        )
    if NldNamespace(namespace).is_root:
        raise NldProjectError(
            f"The root namespace cannot be declared as a namespace folder "
            f"('{NAMESPACE_FACET_FOLDER}: true'): its entities are stored "
            f"directly under the entity path"
        )
    return True


def _load_deploy_mapping(
    namespace: str,
    deploy_facet: Any,
) -> DeployNamespaceMapping:
    """Read the ``deploy`` facet of a namespace, rejecting invalid ones.

    The facet makes a concrete namespace deployable on its own, so it cannot
    apply to a wildcard key: every future namespace matching the pattern
    would silently become deployable, or a member of a group. It must
    declare something — ``unit: true`` or a ``group``.
    """
    if WILDCARD_CHARACTER in namespace:
        raise NldProjectError(
            f"Namespace '{namespace}' is a wildcard pattern and cannot declare "
            f"a '{NAMESPACE_FACET_DEPLOY}' facet: only declared namespaces can "
            f"be deployed on their own or join a deploy group"
        )
    if not isinstance(deploy_facet, dict):
        raise NldProjectError(
            f"The '{NAMESPACE_FACET_DEPLOY}' facet of namespace '{namespace}' "
            f"must be a dictionary, got {type(deploy_facet).__name__}"
        )
    unknown_keys = set(deploy_facet) - set(DeployNamespaceMapping.model_fields)
    if unknown_keys:
        raise NldProjectError(
            f"Unknown keys {sorted(unknown_keys)} in the "
            f"'{NAMESPACE_FACET_DEPLOY}' facet of namespace '{namespace}'. "
            f"Known keys are: {sorted(DeployNamespaceMapping.model_fields)}"
        )
    unit = deploy_facet.get("unit", False)
    if not isinstance(unit, bool):
        raise NldProjectError(
            f"The '{NAMESPACE_FACET_DEPLOY}.unit' of namespace '{namespace}' "
            f"must be true or false, got {unit!r}"
        )
    group = deploy_facet.get("group")
    if group is not None and (not isinstance(group, str) or not group.strip()):
        raise NldProjectError(
            f"The '{NAMESPACE_FACET_DEPLOY}.group' of namespace '{namespace}' "
            f"must be a non-empty string, got {group!r}"
        )
    mapping = DeployNamespaceMapping(
        group=None if group is None else group.strip(),
        unit=unit,
    )
    if not mapping.is_deployable:
        raise NldProjectError(
            f"The '{NAMESPACE_FACET_DEPLOY}' facet of namespace '{namespace}' "
            f"declares nothing: set 'unit: true' to deploy the namespace on "
            f"its own, or a 'group' to deploy it with other namespaces"
        )
    return mapping


def _validate_deploy_groups(deploy_namespace_config: DeployNamespaceConfig) -> None:
    """Reject the deploy groups declared by a single namespace.

    A group exists to deploy several namespaces together, so a group with
    one member is almost always a typo in the other members' group name.
    """
    for group, members in deploy_namespace_config.get_groups().items():
        if len(members) < 2:
            raise NldProjectError(
                f"Deploy group '{group}' is declared by a single namespace "
                f"({members[0]}): a deploy group joins at least two "
                f"namespaces. Check the group name of the other members"
            )


def _validate_folder_namespaces(
    folder_namespaces: list[str],
    entity_registry: NldEntityRegistry,
) -> None:
    """Reject namespace folders whose path collides with an entity folder.

    A folder segment named like a top-level entity folder (``flows``,
    ``structure``, ``templates``, ...) would make a directory readable both
    as an entity folder and as a namespace folder.
    """
    reserved_folder_names = {
        entity_definition.folder_name.split("/")[0]
        for entity_definition in entity_registry.entity_definitions
    } | {SEEDS_FOLDER_NAME}
    for folder_namespace in folder_namespaces:
        for segment in NldNamespace(folder_namespace).split("."):
            if segment in reserved_folder_names:
                raise NldProjectError(
                    f"Namespace folder '{folder_namespace}' uses the segment "
                    f"'{segment}', which is reserved for an entity folder. "
                    f"Reserved names: {sorted(reserved_folder_names)}"
                )


def _register_additional_incremental_types(
    manifests: list[FlowIncrementalTypeManifest],
) -> None:
    """Register external incremental types declared in nld_project.yml.

    Built-in incremental types are seeded in the registry when the impl package
    is imported (see nld.flow.incremental.impl). Importing that package here
    guarantees built-ins are present before we check for name collisions,
    regardless of the order modules were loaded in.
    """
    # Trigger built-in registration so name-collision detection is reliable.
    import nld.flow.incremental.impl  # noqa: F401

    registry = get_flow_incremental_type_registry()
    for manifest in manifests:
        if registry.has(name=manifest.name):
            raise NldProjectError(
                f"Additional incremental type name '{manifest.name}' "
                f"conflicts with an already registered incremental type"
            )
        registry.register(manifest=manifest)


def _register_additional_quality_rules(
    manifests: list[DataQualityRuleManifest],
) -> None:
    """Register external data quality rules declared in nld_project.yml.

    Built-in rules are seeded in the registry when the rules package is
    imported (see nld.flow.quality.rules). Importing that package here
    guarantees built-ins are present before we check for name collisions,
    regardless of the order modules were loaded in.

    Only the manifest is registered here — the ``rule_class`` it points at
    is resolved (imported, validated, instantiated) lazily, the first time
    the rule name is looked up (see DataQualityRuleRegistry.get/has), not
    on project load. This keeps loading a project from requiring another
    project's Python code to be importable purely to inspect its metadata.
    """
    # Trigger built-in registration so name-collision detection is reliable.
    import nld.flow.quality.rules  # noqa: F401

    registry = get_data_quality_rule_registry()
    for manifest in manifests:
        if manifest.name in registry.names():
            raise NldProjectError(
                f"Additional data quality rule name '{manifest.name}' "
                f"conflicts with an already registered rule"
            )
        registry.register_manifest(manifest=manifest)


def _register_additional_alert_transports(
    manifests: list[FlowAlertTransportManifest],
) -> None:
    """Register external alert transports declared in nld_project.yml.

    Built-in transports are seeded in the registry when the transports
    package is imported. Only the manifest is registered here; the class it
    points at is imported lazily on first lookup, like quality rules.
    """
    registry = get_flow_alert_transport_registry()
    for manifest in manifests:
        if manifest.name in registry.names():
            raise NldProjectError(
                f"Additional alert transport name '{manifest.name}' "
                f"conflicts with an already registered transport"
            )
        registry.register_manifest(manifest=manifest)


def _validate_alert_transports(
    scheduling_namespace_config: SchedulingNamespaceConfig,
) -> None:
    """Every declared transport must be known, and accept its settings.

    Checked at load so that a typo in ``alerting.transports`` fails here,
    not silently at run time inside a pod. Names are checked against the
    registry's names without importing anything; settings are checked for
    the transports already resolved (the built-ins) — an external transport
    still pending import is validated when a flow first builds it, so that
    loading a project never imports another project's Python code.
    """
    registry = get_flow_alert_transport_registry()
    errors: list[str] = []
    for namespace, mapping in scheduling_namespace_config.mappings.items():
        alerting = mapping.alerting
        if alerting is None or not alerting.enabled:
            continue
        origin = f"namespaces['{namespace}'].scheduling.alerting"
        for name in alerting.transports:
            if name not in registry.names():
                errors.append(
                    f"{origin} names an unknown transport '{name}'; "
                    f"known transports: {registry.names()}"
                )
                continue
            if registry.is_pending(name=name):
                continue
            errors.extend(
                f"{origin}: {message}"
                for message in registry.get(name=name).validate_settings(
                    settings=alerting.settings_for(transport_name=name),
                )
            )
    if errors:
        raise NldProjectError("\n".join(errors))


class Project(NldBaseModel):
    model_config = {"arbitrary_types_allowed": True}

    additional_entities: list[AdditionalEntityConfig] = Field(default_factory=list)
    additional_entity_paths: list[str] = Field(default_factory=list)
    root_folder_path: str
    name: str
    entity_path: str = "."
    entity_registry: NldEntityRegistry = Field(
        default_factory=lambda: NldEntityRegistry()
    )
    environments: EnvironmentsConfig = Field(default_factory=EnvironmentsConfig)
    metadata_backend_connector: str | None = None
    flow_config: FlowProjectConfig = Field(default_factory=FlowProjectConfig)
    flow_namespace_config: FlowNamespaceConfig = Field(
        default_factory=FlowNamespaceConfig
    )
    folder_namespaces: list[str] = Field(default_factory=list)
    python_additional_paths: dict[str, list[str]] = Field(default_factory=dict)
    scheduling_namespace_config: SchedulingNamespaceConfig = Field(
        default_factory=SchedulingNamespaceConfig
    )
    structure_namespace_config: StructureNamespaceConfig = Field(
        default_factory=StructureNamespaceConfig
    )
    version: str | None = None
    variables: dict[str, str] = Field(default_factory=dict)
    properties: dict[str, str] | None = None
    deploy_namespace_config: DeployNamespaceConfig = Field(
        default_factory=DeployNamespaceConfig
    )

    def override_metadata_backend_connector(
        self,
        connection_name: str | None,
    ) -> None:
        """Point the deployment metadata backend at another connection.

        Sanctioned mutation hook for test harnesses and bootstrap
        tooling that build a Project from fixtures and then bind it to
        a live test connection — instead of bypassing the model's
        immutability with ``object.__setattr__``.
        """
        object.__setattr__(self, "metadata_backend_connector", connection_name)

    @field_validator("python_additional_paths")
    @classmethod
    def validate_python_additional_paths_keys(
        cls,
        value: dict[str, list[str]],
    ) -> dict[str, list[str]]:
        """
        Validate python_additional_paths keys and path formats.

        Ensures:
        - All keys are known
        - Paths do not contain slash separators (must use Python module notation)
        """
        unknown_keys = set(value.keys()) - KNOWN_PYTHON_ADDITIONAL_PATHS_KEYS
        if unknown_keys:
            raise ValueError(
                f"Unknown keys in python_additional_paths: "
                f"{sorted(unknown_keys)}. "
                f"Known keys are: {sorted(KNOWN_PYTHON_ADDITIONAL_PATHS_KEYS)}"
            )

        for key, paths in value.items():
            for path in paths:
                if "/" in path or "\\" in path:
                    raise ValueError(
                        f"Invalid path '{path}' in python_additional_paths['{key}']: "
                        "paths cannot contain slash (/) or backslash (\\). "
                        "Use Python module notation (e.g., 'package.module')"
                    )

        return value

    @property
    def entities_root_folder_path(self) -> str:
        """Get the full path to the entities root folder."""
        return os.path.normpath(os.path.join(self.root_folder_path, self.entity_path))

    @property
    def entity_layout(self) -> NldEntityLayout:
        """Get the on-disk layout of the project entities."""
        return NldEntityLayout(
            entity_path=self.entity_path,
            folder_namespaces=self.folder_namespaces,
        )

    @property
    def additional_entities_root_folder_paths(self) -> list[str]:
        """Resolve the declared additional entity roots to real directories.

        Resolution is deliberately done on access rather than at load time so
        that a project can be read (catalog listing, documentation tooling)
        without every package it references being installed.
        """
        return resolve_additional_entity_paths(
            entity_paths=self.additional_entity_paths,
            root_folder_path=self.root_folder_path,
        )

    @classmethod
    def from_yaml(
        cls,
        root_path: str,
        load_entities: bool = True,
        additional_entity_paths: list[str] | None = None,
    ) -> "Project":
        """Load a project from its ``nld_project.yml``.

        ``additional_entity_paths`` are appended to the ones declared in the
        project file, so an embedding application can contribute entity roots
        the project itself does not know about.
        """
        from_dict = load_project_to_dict(root_path)

        root_folder_path = os.path.normpath(root_path)
        _reject_legacy_config_files(root_path=root_folder_path)
        name = from_dict.get("name")
        version = from_dict.get("version")
        entity_path = from_dict.get("entity_path", ".")
        metadata_backend_connector = from_dict.get("metadata_backend_connector")
        python_additional_paths = from_dict.get("python_additional_paths", {})
        variables = from_dict.get("variables", {})
        properties = from_dict.get("properties")
        environments = EnvironmentsConfig.from_dict(from_dict.get("environments", {}))
        declared_entity_paths = [
            *from_dict.get("additional_entity_paths", []),
            *(additional_entity_paths or []),
        ]

        if not name:
            raise NldProjectError("Project YAML must contain 'name' field")

        additional_entities = [
            AdditionalEntityConfig.model_validate(entry)
            for entry in from_dict.get("additional_entities", [])
        ]

        additional_entity_definitions = []
        builtin_names = {ed.name for ed in ALL_ENTITY_DEFINITIONS}
        for entity_config in additional_entities:
            if entity_config.name in builtin_names:
                raise NldProjectError(
                    f"Additional entity name '{entity_config.name}' "
                    f"conflicts with a built-in entity type"
                )
            additional_entity_definitions.append(entity_config.to_entity_definition())

        flow_config = FlowProjectConfig.model_validate(from_dict.get("flow", {}))
        _register_additional_incremental_types(
            manifests=flow_config.additional_incremental_types,
        )
        _register_additional_quality_rules(
            manifests=flow_config.additional_quality_rules,
        )
        _register_additional_alert_transports(
            manifests=flow_config.additional_alert_transports,
        )

        (
            structure_namespace_config,
            flow_namespace_config,
            scheduling_namespace_config,
            folder_namespaces,
            deploy_namespace_config,
        ) = _load_namespace_configs(
            namespaces=from_dict.get("namespaces", {}),
        )
        _validate_alert_transports(
            scheduling_namespace_config=scheduling_namespace_config,
        )
        entity_registry = NldEntityRegistry(
            additional_entity_definitions=additional_entity_definitions,
        )
        _validate_folder_namespaces(
            folder_namespaces=folder_namespaces,
            entity_registry=entity_registry,
        )

        project = cls(
            additional_entities=additional_entities,
            additional_entity_paths=declared_entity_paths,
            root_folder_path=root_folder_path,
            name=name,
            metadata_backend_connector=metadata_backend_connector,
            version=version,
            entity_path=entity_path,
            python_additional_paths=python_additional_paths,
            variables=variables,
            properties=properties,
            environments=environments,
            entity_registry=entity_registry,
            flow_config=flow_config,
            flow_namespace_config=flow_namespace_config,
            folder_namespaces=folder_namespaces,
            scheduling_namespace_config=scheduling_namespace_config,
            structure_namespace_config=structure_namespace_config,
            deploy_namespace_config=deploy_namespace_config,
        )
        if load_entities:
            project.load_entities()

        return project

    def load_entities(
        self,
        force_reload: bool = False,
        entity_types: list[str] | None = None,
        namespace: str | None = None,
    ) -> None:
        """Load project entities, optionally restricted to the given entity types.

        When ``entity_types`` is provided, only those types and their transitively
        required dependencies are loaded; otherwise every entity type is loaded.
        When ``namespace`` is provided, only the namespaces related to it (its
        ancestors, itself and its descendants) are loaded, and namespace folders
        outside that lineage are not read at all.
        Entities coming from ``additional_entity_paths`` are loaded first, so a
        project entity always overrides a packaged one with the same key.
        """
        requested_entity_definitions = (
            None
            if entity_types is None
            else self.entity_registry.resolve_entity_definitions(
                entity_names=entity_types,
            )
        )
        self.entity_registry.load_entities(
            root_directory=self.entities_root_folder_path,
            force_reload=force_reload,
            requested_entity_definitions=requested_entity_definitions,
            additional_root_directories=self.additional_entities_root_folder_paths,
            entity_layout=self.entity_layout,
            namespace=namespace,
        )
        self._apply_structure_config_tags()

    def _apply_structure_config_tags(self) -> None:
        """Inject namespace-level tags from structure config into structures."""
        all_structures = self.entity_registry.get_structure_dict()
        for namespaced_structure in all_structures.values():
            mapping = self.structure_namespace_config.find_mapping(
                namespace=namespaced_structure.namespace,
            )
            if mapping is None:
                continue
            for tag in mapping.tags:
                if tag not in namespaced_structure.model.tags:
                    namespaced_structure.model.tags.append(tag)

    @property
    def flows_python_additional_paths(self) -> list[str]:
        return self.python_additional_paths.get("flows", [])

    @property
    def sql_transformations_python_additional_paths(self) -> list[str]:
        return self.python_additional_paths.get("sql_transformations", [])
