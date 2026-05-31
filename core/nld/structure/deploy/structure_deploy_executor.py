from __future__ import annotations

import os
from typing import Any, ClassVar, cast

from nld.connector.base.connector import SQLDataConnector
from nld.exceptions import NldRuntimeException
from nld.parameters.execution_params_def import ExecutionParameterDefinition
from nld.pydantic.namespace import NldNamespace
from nld.structure.deploy.structure_deploy_manager import StructureDeployManager
from nld.structure.deploy.structure_deploy_manifest import (
    StructureDeployAction,
    StructureDeployManifest,
    StructureDeployManifestEntry,
)
from nld.structure.deploy.structure_diff import DiffAction, StructureDiff
from nld.structure.deploy.structure_metadata_backend_manager import (
    StructureMetadataBackendManager,
)
from nld.structure.structure.structure import NamespacedStructure, Structure
from nld.task.base import StandardTask
from nld.utils import resolve_variables
from nld.utils.yaml_util import load_yaml_file_into_dict


class StructureDeployExecutor(StandardTask):
    """Executes structure deployment either from a manifest or inline.

    Supports two modes:
    - from_plan=True: reads a previously generated manifest and deploys
      the structures listed in it.
    - from_plan=False (default): computes diffs and deploys inline,
      replicating the original StructureDeployTask behavior.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(
            name="from_plan",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="manifest_path",
            mandatory=False,
        ),
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
        from_plan: bool = False,
        manifest_path: str | None = None,
        name: str | None = None,
        namespace: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._from_plan = from_plan
        self._manifest_path = manifest_path
        self._name = name
        self._namespace = namespace
        self.execution_context.load_entities()

    def run(self, **kwargs: Any) -> bool:
        """Execute the structure deployment."""
        if self._from_plan:
            return self._run_from_plan()
        return self._run_inline()

    # ------------------------------------------------------------------
    # Mode A: from plan
    # ------------------------------------------------------------------

    def _run_from_plan(self) -> bool:
        """Deploy structures from previously generated manifests."""
        if self._manifest_path is not None:
            manifest_paths = [self._manifest_path]
        else:
            from nld.structure.deploy.structure_manifest_discovery import (
                discover_manifests,
            )

            entities_root = self.execution_context.project.entities_root_folder_path
            manifest_paths = discover_manifests(
                entities_root_folder_path=entities_root,
            )

        if not manifest_paths:
            self.log_info("No deployment manifests found in .deployments/structures/")
            return True

        self.log_info(f"Found {len(manifest_paths)} manifest(s) to process")

        for manifest_path in manifest_paths:
            manifest_data = load_yaml_file_into_dict(
                file_path=manifest_path,
            )
            manifest = StructureDeployManifest(**manifest_data)

            if not self._matches_scope(manifest=manifest):
                self.log_info(
                    f"Skipping manifest '{os.path.basename(manifest_path)}' "
                    f"(scope does not match filters)"
                )
                continue

            self.log_info(f"Executing manifest: {os.path.basename(manifest_path)}")
            self._execute_manifest(manifest=manifest)
            self.log_info(
                f"Manifest '{os.path.basename(manifest_path)}' executed successfully"
            )

        return True

    def _matches_scope(
        self,
        manifest: StructureDeployManifest,
    ) -> bool:
        """Check whether the manifest scope matches the CLI filters.

        When neither --name nor --namespace is provided, all manifests
        match. Otherwise, the manifest's scope must match the provided
        filters.
        """
        if self._name is None and self._namespace is None:
            return True

        if self._name is not None and manifest.scope.name != self._name:
            return False

        if self._namespace is not None and manifest.scope.namespace != self._namespace:
            return False

        return True

    def _execute_manifest(
        self,
        manifest: StructureDeployManifest,
    ) -> None:
        """Execute a single deployment manifest."""
        config = self.execution_context.project.structure_config

        for entry in manifest.entries:
            if entry.action == StructureDeployAction.NONE:
                self.log_info(
                    f"Structure '{entry.structure_name}' has no changes, skipping"
                )
                continue

            self._deploy_structure_from_entry(
                entry=entry,
                config=config,
            )

    def _deploy_structure_from_entry(
        self,
        entry: StructureDeployManifestEntry,
        config: Any,
    ) -> None:
        """Deploy a single structure from a manifest entry.

        Re-validates by computing the actual diff at execute time.
        The manifest entry guides which structures to deploy.
        """
        namespace = entry.namespace
        mapping = config.get_mapping(namespace=namespace)
        schema_name = mapping.schema_name

        connector = cast(
            SQLDataConnector[Any],
            self.execution_context.get_data_connector(
                mapping.default_connection_name,
                open_connection=True,
            ),
        )

        # Resolve metadata connector and schema
        metadata_backend_connector_name = (
            self.execution_context.project.metadata_backend_connector
        )
        if metadata_backend_connector_name is not None:
            metadata_connector = cast(
                SQLDataConnector[Any],
                self.execution_context.get_data_connector(
                    metadata_backend_connector_name,
                    open_connection=True,
                ),
            )
            metadata_schema = schema_name
        else:
            metadata_connector = connector
            metadata_schema = schema_name

        metadata_manager = StructureMetadataBackendManager(
            metadata_connector=metadata_connector,
        )
        metadata_manager.ensure_metadata_tables(
            metadata_schema=metadata_schema,
        )

        variables = resolve_variables(
            project_variables=self.execution_context.project.variables,
        )
        deploy_manager = StructureDeployManager(
            structure_connector=connector,
            deploy_schema=schema_name,
            metadata_backend_connector=metadata_connector,
            metadata_schema=metadata_schema,
            variables=variables,
        )

        # Resolve the structure from the entity registry
        entity_registry = self.execution_context.entity_registry
        namespaced_structure = entity_registry.get_structure(
            entity_key=entry.structure_name,
            namespace=namespace,
        )

        try:
            result = deploy_manager.deploy(
                namespaced_structure=namespaced_structure,
            )
        except Exception as ex:
            msg = f"Error deploying structure '{entry.structure_name}': {ex}"
            raise NldRuntimeException(msg) from ex

        if result.deployed:
            summary = self._build_deploy_summary(
                structure=namespaced_structure.model,
                diff=result.diff,
            )
            self.log_info(summary)
        else:
            self.log_info(f"Structure '{entry.structure_name}' is in sync")

    # ------------------------------------------------------------------
    # Mode B: inline execution
    # ------------------------------------------------------------------

    def _run_inline(self) -> bool:
        """Compute diffs and deploy inline without a manifest."""
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

        sql_connector = cast(
            SQLDataConnector[Any],
            self.execution_context.get_data_connector(
                mapping.default_connection_name,
                open_connection=True,
            ),
        )

        # Resolve metadata connector and schema
        metadata_backend_connector_name = (
            self.execution_context.project.metadata_backend_connector
        )
        if metadata_backend_connector_name is not None:
            metadata_connector = cast(
                SQLDataConnector[Any],
                self.execution_context.get_data_connector(
                    metadata_backend_connector_name,
                    open_connection=True,
                ),
            )
            metadata_schema = schema_name
        else:
            metadata_connector = sql_connector
            metadata_schema = schema_name

        metadata_manager = StructureMetadataBackendManager(
            metadata_connector=metadata_connector,
        )
        metadata_manager.ensure_metadata_tables(
            metadata_schema=metadata_schema,
        )

        variables = resolve_variables(
            project_variables=self.execution_context.project.variables,
        )
        deploy_manager = StructureDeployManager(
            structure_connector=sql_connector,
            deploy_schema=schema_name,
            metadata_backend_connector=metadata_connector,
            metadata_schema=metadata_schema,
            variables=variables,
        )

        for namespaced_structure in structures_to_deploy:
            try:
                result = deploy_manager.deploy(
                    namespaced_structure=namespaced_structure,
                )
            except Exception as ex:
                structure_name = namespaced_structure.model.name
                msg = f"Error deploying structure '{structure_name}': {ex}"
                raise NldRuntimeException(msg) from ex

            if result.deployed:
                summary = self._build_deploy_summary(
                    structure=namespaced_structure.model,
                    diff=result.diff,
                )
                self.log_info(summary)
            else:
                self.log_info(
                    f"Structure '{namespaced_structure.model.name}' is in sync"
                )

        return True

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

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

    def _build_deploy_summary(
        self,
        structure: Structure,
        diff: StructureDiff,
    ) -> str:
        """Build a human-readable summary of deployed changes."""
        if not diff.has_changes() and not diff.is_new_table():
            return (
                f"Structure '{structure.name}' deployed: "
                f"definition updated (no schema changes)"
            )

        field_counts: dict[DiffAction, int] = {}
        for field_diff in diff.field_diffs:
            field_counts[field_diff.action] = field_counts.get(field_diff.action, 0) + 1

        char_counts: dict[DiffAction, int] = {}
        for char_diff in diff.characterisation_diffs:
            char_counts[char_diff.action] = char_counts.get(char_diff.action, 0) + 1

        parts = []
        if DiffAction.ADD in field_counts:
            parts.append(f"{field_counts[DiffAction.ADD]} field(s) added")
        if DiffAction.MODIFY in field_counts:
            parts.append(f"{field_counts[DiffAction.MODIFY]} field(s) modified")
        if DiffAction.DROP in field_counts:
            parts.append(f"{field_counts[DiffAction.DROP]} field(s) dropped")
        if DiffAction.ADD in char_counts:
            parts.append(
                f"{char_counts[DiffAction.ADD]} characterisation(s) added",
            )
        if DiffAction.MODIFY in char_counts:
            parts.append(
                f"{char_counts[DiffAction.MODIFY]} characterisation(s) modified",
            )
        if DiffAction.DROP in char_counts:
            parts.append(
                f"{char_counts[DiffAction.DROP]} characterisation(s) dropped",
            )

        action = "created" if diff.is_new_table() else "deployed"
        if not parts:
            return f"Structure '{structure.name}' {action}"
        detail = ", ".join(parts)
        return f"Structure '{structure.name}' {action}: {detail}"
