from __future__ import annotations

import os
import uuid
from typing import Any, ClassVar, cast

from nld.connector.base.connector import SQLDataConnector
from nld.parameters.execution_params_def import ExecutionParameterDefinition
from nld.pydantic.namespace import NldNamespace
from nld.structure.deploy.structure_deploy_manager import StructureDeployManager
from nld.structure.deploy.structure_deploy_manifest import (
    StructureDeployAction,
    StructureDeployManifest,
    StructureDeployManifestEntry,
    StructureDeployScope,
)
from nld.structure.structure.structure import NamespacedStructure
from nld.task.base import StandardTask
from nld.utils.datetime_util import get_current_datetime
from nld.utils.yaml_util import dump_dict_to_yaml


class StructureDeployPlanner(StandardTask):
    """Computes a deployment plan (manifest) for structures.

    The planner resolves structures to deploy, computes diffs
    against the current database state, and produces a
    StructureDeployManifest describing what needs to change.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(
            name="name",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="namespace",
            mandatory=False,
        ),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        name: str | None = None,
        namespace: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._name = name
        self._namespace = namespace
        self.execution_context.load_entities()

    def run(self, **kwargs: Any) -> StructureDeployManifest:
        """Build and persist the deployment manifest."""
        resolved_namespace = self._resolve_namespace(
            namespace=self._namespace,
            structure_name=self._name,
        )

        structures_to_deploy = self._load_structures_to_deploy(
            namespace=resolved_namespace,
            structure_name=self._name,
        )

        config = self.execution_context.project.structure_config
        mapping = config.get_mapping(namespace=resolved_namespace)
        schema_name = mapping.schema_name

        connector = cast(
            SQLDataConnector[Any],
            self.execution_context.get_data_connector(
                mapping.default_connection_name,
                open_connection=True,
            ),
        )

        deploy_manager = StructureDeployManager(
            structure_connector=connector,
            deploy_schema=schema_name,
        )

        entries: list[StructureDeployManifestEntry] = []
        for namespaced_structure in structures_to_deploy:
            structure = namespaced_structure.model

            try:
                change_set = deploy_manager.compute_change_set(
                    structure=structure,
                )
            except Exception as exc:
                self.log_warn(
                    f"Cannot compute change set for structure '{structure.name}': {exc}"
                )
                continue

            diff = change_set.diff

            if diff.is_new_table():
                action = StructureDeployAction.CREATE
            elif diff.has_changes():
                action = StructureDeployAction.ALTER
            else:
                action = StructureDeployAction.NONE

            entries.append(
                StructureDeployManifestEntry(
                    action=action,
                    characterisation_diffs=diff.characterisation_diffs,
                    field_diffs=diff.field_diffs,
                    namespace=namespaced_structure.namespace,
                    structure_name=structure.name,
                ),
            )

        manifest = StructureDeployManifest(
            created_at=get_current_datetime(),
            entries=entries,
            manifest_id=str(uuid.uuid4()),
            scope=StructureDeployScope(
                name=self._name,
                namespace=self._namespace,
            ),
        )

        manifest_path = self._write_manifest(
            manifest=manifest,
            entities_root_folder_path=(
                self.execution_context.project.entities_root_folder_path
            ),
        )
        self.log_info(f"Deploy manifest written to {manifest_path}")

        return manifest

    def _resolve_namespace(
        self,
        namespace: str | None,
        structure_name: str | None,
    ) -> str:
        """Resolve the effective namespace.

        When a structure_name is provided, retrieves the NamespacedStructure
        from the entity registry and uses its namespace.
        """
        if structure_name is not None:
            entity_registry = self.execution_context.entity_registry
            namespaced_structure = entity_registry.get_structure(
                entity_key=structure_name,
                namespace=namespace,
            )
            return namespaced_structure.namespace
        if namespace is None:
            return NldNamespace.ROOT_VALUE
        return namespace

    def _load_structures_to_deploy(
        self,
        namespace: str,
        structure_name: str | None,
    ) -> list[NamespacedStructure]:
        """Load structures to deploy from the entity registry."""
        from nld.exceptions import NldRuntimeException

        entity_registry = self.execution_context.entity_registry
        if structure_name is not None:
            namespaced = entity_registry.get_structure(
                entity_key=structure_name,
                namespace=namespace,
            )
            if (
                namespaced.model.is_external_source()
                or namespaced.model.is_managed_by_flow_execution()
            ):
                return []
            if not namespaced.model.is_table():
                msg = (
                    f"Structure '{structure_name}' is of type "
                    f"'{namespaced.model.structure_type}' and cannot be deployed. "
                    f"Only TABLE structures are supported"
                )
                raise NldRuntimeException(msg)
            return [namespaced]

        structure_dict = entity_registry.get_structure_dict(
            namespace=namespace,
        )
        structures: list[NamespacedStructure] = []
        for ns in structure_dict.values():
            if (
                ns.model.is_table()
                and not ns.model.is_external_source()
                and not ns.model.is_managed_by_flow_execution()
            ):
                structures.append(ns)
        return structures

    def _write_manifest(
        self,
        manifest: StructureDeployManifest,
        entities_root_folder_path: str,
    ) -> str:
        """Serialize the manifest to a YAML file under .deployments/structures/."""
        from nld.structure.deploy.structure_manifest_discovery import (
            get_deployments_folder_path,
        )

        deploy_dir = get_deployments_folder_path(
            entities_root_folder_path=entities_root_folder_path,
        )
        os.makedirs(deploy_dir, exist_ok=True)

        timestamp = manifest.created_at.strftime("%Y%m%d_%H%M%S")
        scope_suffix = self._build_scope_suffix()
        filename = f"{timestamp}_{scope_suffix}.yaml"
        filepath = os.path.join(deploy_dir, filename)

        manifest_dict = manifest.model_dump(
            mode="json",
            exclude_none=True,
        )
        dump_dict_to_yaml(
            data=manifest_dict,
            file_path=filepath,
        )

        return filepath

    def _build_scope_suffix(self) -> str:
        """Build a filename suffix from the deployment scope."""
        if self._name is not None:
            return f"structure_{self._name}"
        if self._namespace is not None:
            return f"ns_{self._namespace.replace('.', '_')}"
        return "all"
