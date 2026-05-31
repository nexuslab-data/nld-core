import os
import uuid
from typing import Any, ClassVar, cast

from nld.connector.base.connector import SQLDataConnector
from nld.flow.definition.flow_definition import (
    NamespacedDataFlowDefinition,
)
from nld.flow.deploy.flow_definition_hash import (
    compute_flow_definition_hash,
    compute_flow_python_hash,
    compute_flow_sql_hash,
    compute_flow_yaml_hash,
)
from nld.flow.deploy.flow_deploy_diff import FlowDeployAction, FlowHashChanges
from nld.flow.deploy.flow_deploy_manifest import (
    BackfillStrategy,
    DeployLink,
    DeployManifest,
    DeployScope,
    FlowDeployEntry,
    StructureDeployEntry,
)
from nld.flow.deploy.flow_deploy_metadata_manager import FlowDeployMetadataManager
from nld.flow.deploy.flow_deploy_metadata_models import FlowDeployMetadataRow
from nld.flow.graph.data_flow_graph import (
    FLOW_NODE_TYPE,
    DataFlowGraph,
    strip_node_type_prefix,
)
from nld.flow.graph.scoped_data_flow_graph import ScopedDataFlowGraph
from nld.parameters.execution_params_def import ExecutionParameterDefinition
from nld.pydantic import NldNamespace
from nld.structure.deploy import StructureDeployManager
from nld.structure.deploy.structure_deploy_manifest import StructureDeployAction
from nld.structure.deploy.structure_diff import DiffAction, FieldDiff
from nld.task.base import StandardTask
from nld.utils.datetime_util import get_current_datetime
from nld.utils.yaml_util import dump_dict_to_yaml


class FlowDeployPlanner(StandardTask):
    """Computes a deployment plan (manifest) for flows.

    The planner resolves the scoped flows, builds a dependency graph
    using DataFlowGraph, computes hashes, compares against previously
    deployed metadata, and produces a ``DeployManifest`` describing what
    needs to change.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(
            name="downstream",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="interactive",
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
        ExecutionParameterDefinition(
            name="no_backfill",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="upstream",
            mandatory=False,
        ),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        downstream: bool = False,
        interactive: bool = True,
        metadata_manager: FlowDeployMetadataManager | None = None,
        name: str | None = None,
        namespace: str | None = None,
        no_backfill: bool = False,
        persist_manifest: bool = True,
        upstream: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._downstream = downstream
        self._interactive = interactive
        self._name = name
        self._namespace = namespace
        self._no_backfill = no_backfill
        self._persist_manifest = persist_manifest
        self._upstream = upstream

        metadata_backend_connector_name = (
            self.execution_context.project.metadata_backend_connector
        )
        if metadata_backend_connector_name is None:
            raise ValueError(
                "metadata_backend_connector must be set in the project "
                "configuration to use FlowDeployPlanner.",
            )

        self._metadata_backend_connector: SQLDataConnector[Any] = cast(
            SQLDataConnector[Any],
            self.execution_context.get_data_connector(
                metadata_backend_connector_name,
                open_connection=True,
            ),
        )
        self._metadata_manager: FlowDeployMetadataManager = (
            metadata_manager
            if metadata_manager is not None
            else FlowDeployMetadataManager(
                connector=self._metadata_backend_connector,
            )
        )

        metadata_schema = self._metadata_backend_connector.get_active_schema()
        if metadata_schema is None:
            raise ValueError(
                "metadata_backend_connector must have a schema configured. "
                "Set 'schema_name' on the connection credentials.",
            )
        self._metadata_schema = metadata_schema

        self.execution_context.load_entities()

    def run(self, **kwargs: Any) -> DeployManifest:
        """Build and persist the deployment manifest."""
        registry = self.execution_context.entity_registry

        # --- Step 1: Build the full flow graph and resolve scope
        all_flows: dict[str, NamespacedDataFlowDefinition] = (
            registry.get_data_flow_definition_dict(
                namespace=self._namespace,
            )
        )
        graph = DataFlowGraph(flow_dict=all_flows)
        scoped_flow_id_set = self._resolve_scoped_flow_ids(
            graph=graph,
        )

        # --- Step 2: Create scoped graph and topological sort
        scoped_graph = ScopedDataFlowGraph(
            source_graph=graph,
            scoped_flow_ids=scoped_flow_id_set,
        )
        sorted_flow_ids = [
            fid for fid in scoped_graph.topological_sort() if fid in scoped_flow_id_set
        ]

        # --- Step 3: Load previously deployed metadata
        self._metadata_manager.ensure_metadata_tables(
            metadata_schema=self._metadata_schema,
        )
        previously_deployed = self._metadata_manager.get_all_deployed_flows(
            metadata_schema=self._metadata_schema,
            namespace=self._namespace,
        )

        # --- Step 4: Build entries for each flow
        entries: list[FlowDeployEntry] = []
        entities_root = self.execution_context.project.entities_root_folder_path
        entity_path = self.execution_context.project.entity_path
        additional_flow_task_types = (
            self.execution_context.project.flow_config.additional_flow_task_types
        )
        additional_task_paths = (
            self.execution_context.project.flows_python_additional_paths
        )

        for flow_id in sorted_flow_ids:
            namespaced_flow = scoped_graph.get_flow(flow_id=flow_id)
            entry = self._build_flow_entry(
                namespaced_flow=namespaced_flow,
                previously_deployed=previously_deployed,
                entities_root=entities_root,
                entity_path=entity_path,
                additional_flow_task_types=additional_flow_task_types,
                additional_task_paths=additional_task_paths,
            )
            if entry.action != FlowDeployAction.UNCHANGED:
                entries.append(entry)

        # --- Step 4b: Build structure entries
        structure_entries = self._build_structure_entries(
            scoped_graph=scoped_graph,
        )

        # --- Step 4c: Extract dependency links from graph
        links: list[DeployLink] = []
        for source_type, source_id, target_type, target_id in scoped_graph.get_edges():
            links.append(
                DeployLink(
                    source_id=source_id,
                    source_type=source_type,
                    target_id=target_id,
                    target_type=target_type,
                )
            )

        # --- Step 5: Detect REMOVED flows
        current_keys = {
            self._build_flow_key(
                namespace=scoped_graph.get_flow(flow_id=fid).namespace,
                flow_name=scoped_graph.get_flow(flow_id=fid).model.name,
            )
            for fid in scoped_flow_id_set
        }
        for key, metadata_row in previously_deployed.items():
            if key not in current_keys:
                entries.append(
                    FlowDeployEntry(
                        flow_name=metadata_row.flow_name,
                        namespace=metadata_row.namespace,
                        action=FlowDeployAction.REMOVED,
                        backfill_strategy=BackfillStrategy.NONE,
                    )
                )

        # --- Step 6: Assemble manifest and persist
        if not entries and not structure_entries:
            self.log_info("No changes detected — manifest not generated")
            return DeployManifest(
                created_at=get_current_datetime(),
                flows=[],
                links=[],
                manifest_id=str(uuid.uuid4()),
                scope=DeployScope(
                    downstream=self._downstream,
                    flow_name=self._name,
                    namespace=self._namespace,
                    upstream=self._upstream,
                ),
                structures=[],
            )

        self._log_manifest_metrics(
            flow_entries=entries,
            structure_entries=structure_entries,
        )

        manifest = DeployManifest(
            created_at=get_current_datetime(),
            flows=entries,
            links=links,
            manifest_id=str(uuid.uuid4()),
            scope=DeployScope(
                downstream=self._downstream,
                flow_name=self._name,
                namespace=self._namespace,
                upstream=self._upstream,
            ),
            structures=structure_entries,
        )

        if self._persist_manifest:
            manifest_path = self._write_manifest(
                manifest=manifest,
                entities_root_folder_path=(
                    self.execution_context.project.entities_root_folder_path
                ),
            )
            self.log_info(f"Deploy manifest written to {manifest_path}")

        return manifest

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_scoped_flow_ids(
        self,
        graph: DataFlowGraph,
    ) -> set[str]:
        """Resolve flow IDs based on name/namespace/lineage scope.

        Uses DataFlowGraph.get_scoped_subgraph to resolve upstream
        and downstream lineage when requested.
        """
        if not self._upstream and not self._downstream and self._name is not None:
            node_id = graph.resolve_node_id(
                name=self._name,
                namespace=self._namespace,
                node_type=FLOW_NODE_TYPE,
            )
            return {node_id}

        if not self._upstream and not self._downstream:
            return set(graph.flow_ids)

        scoped_graph = graph.get_scoped_subgraph(
            name=self._name,
            namespace=self._namespace,
            node_type=FLOW_NODE_TYPE,
            upstream=self._upstream,
            downstream=self._downstream,
        )

        return set(scoped_graph.flow_ids)

    def _build_flow_entry(
        self,
        namespaced_flow: NamespacedDataFlowDefinition,
        previously_deployed: dict[str, FlowDeployMetadataRow],
        entities_root: str,
        entity_path: str | None,
        additional_flow_task_types: dict[str, str] | None,
        additional_task_paths: list[str] | None,
    ) -> FlowDeployEntry:
        """Build a single FlowDeployEntry with diff info."""
        flow_def = namespaced_flow.model
        namespace = namespaced_flow.namespace
        flow_key = self._build_flow_key(
            namespace=namespace,
            flow_name=flow_def.name,
        )

        # Compute current hashes
        yaml_hash = compute_flow_yaml_hash(flow_definition=flow_def)
        sql_hash = compute_flow_sql_hash(
            entities_root_folder_path=entities_root,
            namespace=namespace,
            flow_name=flow_def.name,
        )
        python_hash = compute_flow_python_hash(
            flow_definition=flow_def,
            namespace=namespace,
            entity_path=entity_path,
            additional_task_paths=additional_task_paths,
            additional_flow_task_types=additional_flow_task_types,
        )
        definition_hash = compute_flow_definition_hash(
            flow_definition=flow_def,
            entities_root_folder_path=entities_root,
            namespace=namespace,
            entity_path=entity_path,
            additional_task_paths=additional_task_paths,
            additional_flow_task_types=additional_flow_task_types,
        )

        # Determine action by comparing with previous deployment
        prev_metadata = previously_deployed.get(flow_key)
        if prev_metadata is None:
            action = FlowDeployAction.NEW
            hash_changes = FlowHashChanges(
                python_changed=True,
                sql_changed=True,
                yaml_changed=True,
            )
        elif prev_metadata.flow_definition_hash != definition_hash:
            action = FlowDeployAction.CHANGED
            hash_changes = FlowHashChanges(
                python_changed=prev_metadata.flow_python_hash != python_hash,
                sql_changed=prev_metadata.flow_sql_hash != sql_hash,
                yaml_changed=prev_metadata.flow_yaml_hash != yaml_hash,
            )
        else:
            action = FlowDeployAction.UNCHANGED
            hash_changes = None

        # Default backfill strategy
        if self._no_backfill or action == FlowDeployAction.UNCHANGED:
            backfill_strategy = BackfillStrategy.NONE
        else:
            backfill_strategy = BackfillStrategy.FULL

        return FlowDeployEntry(
            flow_name=flow_def.name,
            namespace=namespace,
            action=action,
            backfill_strategy=backfill_strategy,
            hash_changes=hash_changes,
        )

    def _build_structure_entries(
        self,
        scoped_graph: ScopedDataFlowGraph,
    ) -> list[StructureDeployEntry]:
        """Build structure entries for all in-scope structures."""
        structure_entries: list[StructureDeployEntry] = []

        for structure_id in scoped_graph.scoped_structure_ids:
            # Find all in-scope flows that target this structure
            targeting_flow_ids: list[str] = []
            for predecessor in scoped_graph.digraph.predecessors(structure_id):  # type: ignore[no-untyped-call]
                pred_data = scoped_graph.digraph.nodes[predecessor]
                if (
                    pred_data.get(scoped_graph.NODE_TYPE_ATTRIBUTE) == FLOW_NODE_TYPE
                    and predecessor in scoped_graph.scoped_flow_ids
                ):
                    targeting_flow_ids.append(predecessor)

            if not targeting_flow_ids:
                continue

            # Use any targeting flow to resolve the structure
            ref_flow = scoped_graph.get_flow(flow_id=targeting_flow_ids[0])
            ref_flow_def = ref_flow.model

            try:
                desired_structure = ref_flow_def.resolve_target_structure()
            except Exception as exc:
                self.log_warn(
                    f"Cannot resolve target_structure for structure "
                    f"'{structure_id}': {exc}"
                )
                continue

            if (
                not desired_structure.is_table()
                or desired_structure.is_external_source()
                or desired_structure.is_managed_by_flow_execution()
            ):
                continue

            # Derive namespace from the structure's entity_id, not the flow
            structure_entity_id = strip_node_type_prefix(structure_id)
            namespace = self._extract_namespace_from_entity_id(
                entity_id=structure_entity_id,
                entity_name=desired_structure.name,
            )

            structure_config = self.execution_context.project.structure_config
            mapping = structure_config.get_mapping(namespace=namespace)
            connector_name = mapping.default_connection_name

            try:
                connector = self.execution_context.get_data_connector(
                    connector_name,
                    open_connection=True,
                )
            except Exception as exc:
                self.log_warn(
                    f"Cannot open connector '{connector_name}' for structure "
                    f"'{structure_id}': {exc}"
                )
                continue

            schema_name = mapping.schema_name
            sql_connector = cast(SQLDataConnector[Any], connector)
            deploy_manager = StructureDeployManager(
                structure_connector=sql_connector,
                deploy_schema=schema_name,
            )

            try:
                change_set = deploy_manager.compute_change_set(
                    structure=desired_structure,
                )
            except Exception:
                continue

            diff = change_set.diff

            if diff.is_new_table():
                structure_action = StructureDeployAction.CREATE
            elif diff.has_changes():
                structure_action = StructureDeployAction.ALTER
            else:
                continue

            self._warn_rename_candidates(
                structure_name=desired_structure.name,
                field_diffs=diff.field_diffs,
            )

            structure_entries.append(
                StructureDeployEntry(
                    action=structure_action,
                    characterisation_diffs=diff.characterisation_diffs,
                    field_diffs=diff.field_diffs,
                    namespace=namespace,
                    structure_name=desired_structure.name,
                ),
            )

        return structure_entries

    def _warn_rename_candidates(
        self,
        structure_name: str,
        field_diffs: list[FieldDiff],
    ) -> None:
        """Log a warning when simultaneous ADD and DROP suggest a possible rename.

        Field renaming is not managed automatically. Users should
        populate the ``field_naming_change_mapping`` attribute on the
        StructureDeployEntry in the manifest if a rename is intended.
        """
        dropped = [fd for fd in field_diffs if fd.action == DiffAction.DROP]
        added = [fd for fd in field_diffs if fd.action == DiffAction.ADD]

        if not dropped or not added:
            return

        drop_names = ", ".join(fd.field_name for fd in dropped)
        add_names = ", ".join(fd.field_name for fd in added)
        self.log_warn(
            f"Structure '{structure_name}': simultaneous DROP ({drop_names}) "
            f"and ADD ({add_names}) detected. If this is a field rename, "
            f"set the 'field_naming_change_mapping' attribute in the "
            f"manifest entry."
        )

    @staticmethod
    def _extract_namespace_from_entity_id(
        entity_id: str,
        entity_name: str,
    ) -> str:
        """Extract the namespace from a graph entity_id.

        Entity IDs follow the format ``namespace.entity_name``
        or just ``entity_name`` for root namespace entities.
        """
        if entity_id == entity_name:
            return "."
        return entity_id[: -(len(entity_name) + 1)]

    def _build_flow_key(
        self,
        namespace: str,
        flow_name: str,
    ) -> str:
        """Build a unique key from namespace and flow name."""
        if NldNamespace(namespace).is_root:
            return flow_name
        return f"{namespace}.{flow_name}"

    def _log_manifest_metrics(
        self,
        flow_entries: list[FlowDeployEntry],
        structure_entries: list[StructureDeployEntry],
    ) -> None:
        """Log a summary of flow and structure counts by action."""
        flow_counts: dict[str, int] = {}
        for flow_entry in flow_entries:
            action = flow_entry.action.value
            flow_counts[action] = flow_counts.get(action, 0) + 1

        flow_parts = [f"{count} {action}" for action, count in flow_counts.items()]
        self.log_info(f"Flows: {', '.join(flow_parts)}" if flow_parts else "Flows: 0")

        structure_counts: dict[str, int] = {}
        for structure_entry in structure_entries:
            action = structure_entry.action.value
            structure_counts[action] = structure_counts.get(action, 0) + 1

        structure_parts = [
            f"{count} {action}" for action, count in structure_counts.items()
        ]
        self.log_info(
            f"Structures: {', '.join(structure_parts)}"
            if structure_parts
            else "Structures: 0",
        )

    def _write_manifest(
        self,
        manifest: DeployManifest,
        entities_root_folder_path: str,
    ) -> str:
        """Serialize the manifest to a YAML file under .deployments/flows/."""
        from nld.flow.deploy.flow_manifest_discovery import get_deployments_folder_path

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
            return f"flow_{self._name}"
        if self._namespace is not None:
            return f"ns_{self._namespace.replace('.', '_')}"
        return "all"
