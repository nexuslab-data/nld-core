import os
from typing import Any

from pydantic import Field, field_validator

from nld.flow.config import FlowProjectConfig
from nld.flow.incremental.models import FlowIncrementalTypeManifest
from nld.flow.incremental.services.registry import (
    get_flow_incremental_type_registry,
)
from nld.pydantic import NldBaseModel
from nld.service.nld_entity_registry import ALL_ENTITY_DEFINITIONS, NldEntityRegistry
from nld.structure.config.structure_config import StructureProjectConfig
from nld.utils.yaml_util import load_yaml_file_into_dict

from .additional_entity_config import AdditionalEntityConfig
from .environment_config import EnvironmentsConfig
from .project_exceptions import (
    NldMissingProjectYamlFile,
    NldProjectError,
)

NLD_PROJECT_FILENAME = "nld_project.yml"
FLOW_CONFIG_FILENAME = "config/flow.yaml"
STRUCTURE_CONFIG_FILENAME = "config/structure.yaml"
KNOWN_PYTHON_ADDITIONAL_PATHS_KEYS = {"flows", "sql_transformations"}


def load_project_to_dict(root_path: str) -> dict[str, Any]:
    root_path = os.path.normpath(root_path)
    project_filepath = os.path.join(root_path, NLD_PROJECT_FILENAME)

    if not os.path.exists(project_filepath):
        raise NldMissingProjectYamlFile(path=project_filepath)

    project_dict = load_yaml_file_into_dict(project_filepath)

    if not isinstance(project_dict, dict):
        raise NldProjectError(f"{NLD_PROJECT_FILENAME} does not parse to a dictionary")

    return project_dict


def _load_flow_config(root_path: str) -> FlowProjectConfig:
    """Load FlowProjectConfig from config/flow.yaml if available."""
    config_path = os.path.join(root_path, FLOW_CONFIG_FILENAME)
    if not os.path.exists(config_path):
        return FlowProjectConfig(mappings={})
    with open(config_path) as fh:
        return FlowProjectConfig.from_yaml(fh.read())


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


def _load_structure_config(root_path: str) -> StructureProjectConfig:
    """Load StructureProjectConfig from config/structure.yaml if available."""
    config_path = os.path.join(root_path, STRUCTURE_CONFIG_FILENAME)
    if not os.path.exists(config_path):
        return StructureProjectConfig(mappings={})
    with open(config_path) as fh:
        return StructureProjectConfig.from_yaml(fh.read())


class Project(NldBaseModel):
    model_config = {"arbitrary_types_allowed": True}

    additional_entities: list[AdditionalEntityConfig] = Field(default_factory=list)
    additional_incremental_types: list[FlowIncrementalTypeManifest] = Field(
        default_factory=list,
    )
    root_folder_path: str
    name: str
    entity_path: str = "."
    entity_registry: NldEntityRegistry = Field(
        default_factory=lambda: NldEntityRegistry()
    )
    environments: EnvironmentsConfig = Field(default_factory=EnvironmentsConfig)
    metadata_backend_connector: str | None = None
    flow_config: FlowProjectConfig = Field(
        default_factory=lambda: FlowProjectConfig(mappings={})
    )
    python_additional_paths: dict[str, list[str]] = Field(default_factory=dict)
    structure_config: StructureProjectConfig = Field(
        default_factory=lambda: StructureProjectConfig(mappings={})
    )
    version: str | None = None
    variables: dict[str, str] = Field(default_factory=dict)
    properties: dict[str, str] | None = None

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

    @classmethod
    def from_yaml(
        cls,
        root_path: str,
        load_entities: bool = True,
    ) -> "Project":
        from_dict = load_project_to_dict(root_path)

        root_folder_path = os.path.normpath(root_path)
        name = from_dict.get("name")
        version = from_dict.get("version")
        entity_path = from_dict.get("entity_path", ".")
        metadata_backend_connector = from_dict.get("metadata_backend_connector")
        python_additional_paths = from_dict.get("python_additional_paths", {})
        variables = from_dict.get("variables", {})
        properties = from_dict.get("properties")
        environments = EnvironmentsConfig.from_dict(from_dict.get("environments", {}))

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

        additional_incremental_types = [
            FlowIncrementalTypeManifest.model_validate(entry)
            for entry in from_dict.get("additional_incremental_types", [])
        ]
        _register_additional_incremental_types(
            manifests=additional_incremental_types,
        )

        flow_config = _load_flow_config(
            root_path=root_folder_path,
        )
        structure_config = _load_structure_config(
            root_path=root_folder_path,
        )

        project = cls(
            additional_entities=additional_entities,
            additional_incremental_types=additional_incremental_types,
            root_folder_path=root_folder_path,
            name=name,
            metadata_backend_connector=metadata_backend_connector,
            version=version,
            entity_path=entity_path,
            python_additional_paths=python_additional_paths,
            variables=variables,
            properties=properties,
            environments=environments,
            entity_registry=NldEntityRegistry(
                additional_entity_definitions=additional_entity_definitions,
            ),
            flow_config=flow_config,
            structure_config=structure_config,
        )
        if load_entities:
            project.load_entities()

        return project

    def load_entities(
        self,
        force_reload: bool = False,
        entity_types: list[str] | None = None,
    ) -> None:
        """Load project entities, optionally restricted to the given entity types.

        When ``entity_types`` is provided, only those types and their transitively
        required dependencies are loaded; otherwise every entity type is loaded.
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
        )
        self._apply_structure_config_tags()

    def _apply_structure_config_tags(self) -> None:
        """Inject namespace-level tags from structure config into structures."""
        all_structures = self.entity_registry.get_structure_dict()
        for namespaced_structure in all_structures.values():
            try:
                mapping = self.structure_config.get_mapping(
                    namespace=namespaced_structure.namespace,
                )
            except ValueError:
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
