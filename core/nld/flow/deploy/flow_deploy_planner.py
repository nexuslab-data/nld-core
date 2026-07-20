import uuid
from typing import Any, ClassVar, cast

from nld.connector.base.connector import SQLDataConnector
from nld.deploy.change_file_loader import (
    ChangeFileError,
    get_flow_renames,
    group_backfill_defaults_by_structure,
    group_field_renames_by_structure,
    group_structure_renames_by_source,
    group_structure_renames_by_target,
    resolve_pending_change_files,
    validate_backfill_default_targets,
)
from nld.deploy.change_file_models import PendingChangeFile
from nld.deploy.change_log_manager import DeploymentChangeLogManager
from nld.exceptions import NldRuntimeException
from nld.flow.definition.flow_definition import (
    NamespacedDataFlowDefinition,
)
from nld.flow.deploy.flow_change_set import (
    DeployLink,
    DeployScope,
    FlowChangeEntry,
    FlowChangeSet,
)
from nld.flow.deploy.flow_definition_hash import (
    compute_flow_definition_hash,
    compute_flow_python_hash,
    compute_flow_sql_hash,
    compute_flow_yaml_hash,
)
from nld.flow.deploy.flow_deploy_diff import FlowDeployAction, FlowHashChanges
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
from nld.pydantic.namespace import build_entity_key
from nld.service import EntityTypeNames
from nld.structure.deploy import StructureMetadataBackendManager
from nld.structure.deploy.deploy_target_factory import StructureDeployTargetFactory
from nld.structure.deploy.structure_change import (
    StructureChangeEntry,
    StructureDeployAction,
)
from nld.structure.deploy.structure_drift import DeploymentDriftError
from nld.task.base import StandardTask
from nld.utils import resolve_variables
from nld.utils.datetime_util import get_current_datetime


class FlowDeployPlanner(StandardTask):
    """Computes the in-memory change set for a flow deployment.

    The planner resolves the scoped flows, builds a dependency graph
    using DataFlowGraph, computes hashes, compares against previously
    deployed metadata, and produces a ``FlowChangeSet`` describing what
    needs to change. The change set is never persisted (design: the
    diff is always recomputed against the live target).
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(
            name="adopt",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="allow_drift",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="downstream",
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
            name="rebuild",
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
        adopt: bool = False,
        allow_drift: bool = False,
        deploy_target_factory: StructureDeployTargetFactory | None = None,
        downstream: bool = False,
        metadata_manager: FlowDeployMetadataManager | None = None,
        name: str | None = None,
        namespace: str | None = None,
        rebuild: bool = False,
        upstream: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._adopt = adopt
        self._allow_drift = allow_drift
        self._downstream = downstream
        self._name = name
        self._namespace = namespace
        self._rebuild = rebuild
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

        self._deploy_target_factory = deploy_target_factory

        self.execution_context.load_entities(
            entity_types=[EntityTypeNames.DATA_FLOW_DEFINITION]
        )

    @property
    def deploy_target_factory(self) -> StructureDeployTargetFactory:
        """The run's shared per-(connection, schema) manager factory.

        The orchestrator passes the same factory to the executor so
        applying reuses the managers — and prefetched snapshots —
        planning already built. Built lazily on first use.
        """
        if self._deploy_target_factory is None:
            self._deploy_target_factory = StructureDeployTargetFactory(
                connector_resolver=self._resolve_sql_connector,
                metadata_connector=self._metadata_backend_connector,
                metadata_schema=self._metadata_schema,
                variables=resolve_variables(
                    project_variables=self.execution_context.project.variables,
                ),
            )
        return self._deploy_target_factory

    def _resolve_sql_connector(
        self,
        connection_name: str,
    ) -> SQLDataConnector[Any]:
        """Open (or reuse) a named SQL connector from the execution context."""
        return cast(
            SQLDataConnector[Any],
            self.execution_context.get_data_connector(
                connection_name,
                open_connection=True,
            ),
        )

    def run(self, **kwargs: Any) -> FlowChangeSet:
        """Compute the in-memory change set for the resolved scope."""
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

        # --- Step 3: Load previously deployed metadata + pending change files
        self._metadata_manager.ensure_metadata_tables(
            metadata_schema=self._metadata_schema,
        )
        StructureMetadataBackendManager(
            metadata_connector=self._metadata_backend_connector,
        ).ensure_metadata_tables(
            metadata_schema=self._metadata_schema,
        )
        previously_deployed = self._metadata_manager.get_all_deployed_flows(
            metadata_schema=self._metadata_schema,
            namespace=self._namespace,
        )
        pending_change_files = self._load_pending_change_files()
        self._remap_renamed_flows(
            previously_deployed=previously_deployed,
            pending_change_files=pending_change_files,
        )
        self._validate_backfill_default_targets(
            pending_change_files=pending_change_files,
        )

        # --- Step 4: Build entries for each flow
        entries: list[FlowChangeEntry] = []
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
            pending_change_files=pending_change_files,
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
                    FlowChangeEntry(
                        flow_name=metadata_row.flow_name,
                        namespace=metadata_row.namespace,
                        action=FlowDeployAction.REMOVED,
                    )
                )

        scope = DeployScope(
            downstream=self._downstream,
            flow_name=self._name,
            namespace=self._namespace,
            upstream=self._upstream,
        )

        if not entries and not structure_entries and not pending_change_files:
            self.log_info("No changes detected — empty change set")
            return FlowChangeSet(
                changeset_id=str(uuid.uuid4()),
                created_at=get_current_datetime(),
                flows=[],
                links=[],
                pending_change_files=[],
                scope=scope,
                structures=[],
            )

        self._log_change_set_metrics(
            flow_entries=entries,
            structure_entries=structure_entries,
        )

        return FlowChangeSet(
            changeset_id=str(uuid.uuid4()),
            created_at=get_current_datetime(),
            flows=entries,
            links=links,
            pending_change_files=pending_change_files,
            scope=scope,
            structures=structure_entries,
        )

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
    ) -> FlowChangeEntry:
        """Build a single FlowChangeEntry with diff info."""
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

        return FlowChangeEntry(
            flow_name=flow_def.name,
            namespace=namespace,
            action=action,
            hash_changes=hash_changes,
        )

    def _load_pending_change_files(self) -> list[PendingChangeFile]:
        """Load the pending deployment change files for this target."""
        change_log_manager = DeploymentChangeLogManager(
            connector=self._metadata_backend_connector,
        )
        change_log_manager.ensure_table(
            metadata_schema=self._metadata_schema,
        )
        pending = resolve_pending_change_files(
            project_root_folder_path=(
                self.execution_context.project.entities_root_folder_path
            ),
            applied_hashes_by_change_id=change_log_manager.get_applied_hashes(
                metadata_schema=self._metadata_schema,
            ),
        )
        if pending:
            pending_ids = ", ".join(change.change_id for change in pending)
            self.log_info(f"Pending deployment change file(s): {pending_ids}")
        return pending

    def _remap_renamed_flows(
        self,
        previously_deployed: dict[str, FlowDeployMetadataRow],
        pending_change_files: list[PendingChangeFile],
    ) -> None:
        """Move recorded flow rows to their declared new names.

        Without the remap a declared flow rename reads as REMOVED old
        flow plus NEW flow; with it the new-name flow compares against
        the old recorded hashes.
        """
        for directive in get_flow_renames(
            pending_change_files=pending_change_files,
        ):
            if (
                directive.from_name in previously_deployed
                and directive.to not in previously_deployed
            ):
                moved_row = previously_deployed.pop(directive.from_name)
                to_namespace, _, to_flow_name = directive.to.rpartition(".")
                # Move the row to its new key AND carry its identity
                # fields to the new name: an out-of-scope rename target
                # is otherwise emitted as a REMOVED entry under its
                # stale name, colliding with a flow reclaiming that name.
                previously_deployed[directive.to] = moved_row.model_copy(
                    update={
                        "namespace": to_namespace or ".",
                        "flow_name": to_flow_name,
                    },
                )

    def _validate_backfill_default_targets(
        self,
        pending_change_files: list[PendingChangeFile],
    ) -> None:
        """Refuse a backfill_default directive that targets a view."""
        backfill_defaults_by_structure = group_backfill_defaults_by_structure(
            pending_change_files=pending_change_files,
        )
        if not backfill_defaults_by_structure:
            return
        validate_backfill_default_targets(
            backfill_defaults_by_structure=backfill_defaults_by_structure,
            entity_registry=self.execution_context.entity_registry,
        )

    @staticmethod
    def _build_failed_entry(
        structure_entity_id: str,
        planning_error: str,
    ) -> StructureChangeEntry:
        """Build a FAILED entry for a structure whose planning raised.

        Used before the desired structure could be resolved, so the
        namespace and name are split from the graph entity id.
        """
        namespace, _, structure_name = structure_entity_id.rpartition(".")
        return StructureChangeEntry(
            action=StructureDeployAction.FAILED,
            namespace=namespace or NldNamespace.ROOT_VALUE,
            planning_error=planning_error,
            structure_name=structure_name,
        )

    def _build_structure_entries(
        self,
        scoped_graph: ScopedDataFlowGraph,
        pending_change_files: list[PendingChangeFile],
    ) -> list[StructureChangeEntry]:
        """Build structure entries for all in-scope structures."""
        structure_entries: list[StructureChangeEntry] = []
        renames_by_structure = group_field_renames_by_structure(
            pending_change_files=pending_change_files,
        )
        structure_renames_by_target = group_structure_renames_by_target(
            pending_change_files=pending_change_files,
        )
        structure_renames_by_source = group_structure_renames_by_source(
            pending_change_files=pending_change_files,
        )
        backfill_defaults_by_structure = group_backfill_defaults_by_structure(
            pending_change_files=pending_change_files,
        )

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
                error_msg = (
                    f"Cannot resolve target_structure for structure "
                    f"'{structure_id}': {exc}"
                )
                self.log_error(error_msg)
                structure_entries.append(
                    self._build_failed_entry(
                        structure_entity_id=strip_node_type_prefix(structure_id),
                        planning_error=error_msg,
                    ),
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
                deploy_manager = self.deploy_target_factory.get_manager(
                    connection_name=connector_name,
                    schema_name=mapping.schema_name,
                )
            except Exception as exc:
                error_msg = (
                    f"Cannot open connector '{connector_name}' for structure "
                    f"'{structure_id}': {exc}"
                )
                self.log_error(error_msg)
                structure_entries.append(
                    StructureChangeEntry(
                        action=StructureDeployAction.FAILED,
                        namespace=namespace,
                        planning_error=error_msg,
                        structure_name=desired_structure.name,
                    ),
                )
                continue

            if self._rebuild:
                rebuild_statements = deploy_manager.compute_rebuild_statements(
                    structure=desired_structure,
                )
                structure_entries.append(
                    StructureChangeEntry(
                        action=StructureDeployAction.CREATE,
                        ddl_statements=[st.sql for st in rebuild_statements],
                        namespace=namespace,
                        structure_name=desired_structure.name,
                    ),
                )
                continue

            try:
                change_set = deploy_manager.compute_change_set(
                    structure=desired_structure,
                    allow_drift=self._allow_drift or self._adopt,
                    namespace=namespace,
                    pending_field_renames=renames_by_structure.get(
                        structure_entity_id,
                        [],
                    ),
                    pending_structure_renames=structure_renames_by_target.get(
                        structure_entity_id,
                        [],
                    ),
                    pending_claiming_renames=[
                        directive
                        for directive in structure_renames_by_source.get(
                            structure_entity_id,
                            [],
                        )
                        if directive.to != structure_entity_id
                    ],
                )
            except (ChangeFileError, DeploymentDriftError):
                raise
            except Exception as exc:
                error_msg = (
                    f"Change set computation failed for structure "
                    f"'{structure_entity_id}': {exc}"
                )
                self.log_error(error_msg)
                structure_entries.append(
                    StructureChangeEntry(
                        action=StructureDeployAction.FAILED,
                        namespace=namespace,
                        planning_error=error_msg,
                        structure_name=desired_structure.name,
                    ),
                )
                continue

            diff = change_set.diff

            if diff.is_new_table():
                structure_action = StructureDeployAction.CREATE
            elif change_set.rebuild_required:
                structure_action = StructureDeployAction.REBUILD
            elif diff.has_changes() or change_set.statements:
                # A pure declared rename yields no name-based diff but
                # still carries the rename DDL to apply.
                structure_action = StructureDeployAction.ALTER
            elif structure_entity_id in backfill_defaults_by_structure:
                # No schema diff, but a pending one-shot default fill
                # still needs the structure entry so the executor
                # reaches and applies it.
                structure_action = StructureDeployAction.NONE
            elif self._adopt:
                # No schema diff either, but under --adopt the
                # structure must still reach the executor: an
                # out-of-band table that already matches the desired
                # asset exactly has no diff to report, yet its schema
                # was never recorded in the backend (bootstrap: the
                # metadata tables start empty). Without this entry the
                # executor never calls StructureDeployManager.deploy(),
                # so _adopt_current_state() never runs and the
                # structure keeps zero backend history forever — this
                # is the common case adopt exists to handle.
                structure_action = StructureDeployAction.NONE
            else:
                continue

            view_flows_to_execute: list[str] = []
            if change_set.dependent_views:
                view_flows_to_execute = self._resolve_view_flows(
                    view_names=list(reversed(change_set.dependent_views)),
                    table_name=desired_structure.name,
                )

            structure_entries.append(
                StructureChangeEntry(
                    action=structure_action,
                    characterisation_diffs=diff.characterisation_diffs,
                    ddl_statements=[st.sql for st in change_set.statements],
                    dependent_views=change_set.dependent_views,
                    field_diffs=diff.field_diffs,
                    namespace=namespace,
                    structure_name=desired_structure.name,
                    view_flows_to_execute=view_flows_to_execute,
                ),
            )

        return structure_entries

    def _resolve_view_flows(
        self,
        view_names: list[str],
        table_name: str,
    ) -> list[str]:
        """Map dependent views to the VIEW flows that recreate them.

        Recreation is a forced re-execution of the view-creating
        flows, in dependency order (shallowest first). A dependent
        view no flow manages cannot be recreated: the deploy fails
        before anything is dropped.
        """
        registry = self.execution_context.entity_registry
        all_flows = registry.get_data_flow_definition_dict(
            namespace=self._namespace,
        )

        flow_by_view_name: dict[str, str] = {}
        for namespaced_flow in all_flows.values():
            flow_def = namespaced_flow.model
            if flow_def.write_strategy != "VIEW":
                continue
            try:
                target_name = flow_def.resolve_target_structure().name
            except Exception:
                continue
            flow_by_view_name[target_name] = self._build_flow_key(
                namespace=namespaced_flow.namespace,
                flow_name=flow_def.name,
            )

        unmanaged = [name for name in view_names if name not in flow_by_view_name]
        if unmanaged:
            unmanaged_names = ", ".join(unmanaged)
            raise NldRuntimeException(
                f"Changing structure '{table_name}' requires dropping "
                f"dependent view(s) [{unmanaged_names}] that no nld VIEW "
                "flow manages — they cannot be recreated automatically. "
                "Drop or take over these views explicitly before deploying.",
            )
        return [flow_by_view_name[name] for name in view_names]

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
        return build_entity_key(namespace=namespace, entity_name=flow_name)

    def _log_change_set_metrics(
        self,
        flow_entries: list[FlowChangeEntry],
        structure_entries: list[StructureChangeEntry],
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
