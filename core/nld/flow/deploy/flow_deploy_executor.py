import os
import uuid
from typing import Any, ClassVar, cast

from nld.connector.base.connector import SQLDataConnector
from nld.flow.definition.flow_definition import NamespacedDataFlowDefinition
from nld.flow.deploy.flow_deploy_diff import FlowDeployAction
from nld.flow.deploy.flow_deploy_manifest import (
    BackfillStrategy,
    DeployManifest,
    FlowDeployEntry,
    StructureDeployEntry,
)
from nld.flow.deploy.flow_deploy_metadata_manager import FlowDeployMetadataManager
from nld.flow.deploy.flow_deploy_metadata_models import (
    FlowDeployHistoryRow,
    FlowDeploymentFlowChangeRow,
    FlowDeploymentRow,
    FlowDeploymentStructureChangeRow,
    FlowDeployMetadataRow,
)
from nld.flow.execution.execution_info import FlowExecutionInfo
from nld.flow.task.data_flow_executor import DataFlowExecutor
from nld.parameters.execution_params_def import ExecutionParameterDefinition
from nld.pydantic import NldNamespace
from nld.structure.deploy import StructureDeployManager, StructureMetadataBackendManager
from nld.structure.deploy.structure_deploy_manifest import StructureDeployAction
from nld.task.base import StandardTask
from nld.utils import resolve_variables
from nld.utils.datetime_util import get_current_datetime
from nld.utils.yaml_util import load_yaml_file_into_dict


class FlowDeployResult:
    """Aggregated result of a deploy execution."""

    def __init__(
        self,
        deployment_id: str = "",
    ) -> None:
        self.deployed: list[FlowDeployEntry] = []
        self.deployment_id = deployment_id
        self.failed: dict[str, str] = {}
        self.flow_results: list[FlowExecutionInfo] = []
        self.skipped: dict[str, str] = {}
        self.structures_deployed: list[str] = []
        self.structures_failed: dict[str, str] = {}
        self.structures_skipped: dict[str, str] = {}

    @property
    def total(self) -> int:
        return len(self.deployed) + len(self.failed) + len(self.skipped)

    @property
    def succeeded_count(self) -> int:
        return len(self.deployed)

    @property
    def failed_count(self) -> int:
        return len(self.failed)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @property
    def structures_total(self) -> int:
        return (
            len(self.structures_deployed)
            + len(self.structures_failed)
            + len(self.structures_skipped)
        )

    @property
    def structures_succeeded_count(self) -> int:
        return len(self.structures_deployed)

    @property
    def structures_failed_count(self) -> int:
        return len(self.structures_failed)

    @property
    def structures_skipped_count(self) -> int:
        return len(self.structures_skipped)


class FlowDeployExecutor(StandardTask):
    """Applies pre-built deployment manifests.

    Given an in-memory ``DeployManifest`` (set via ``manifest=...``), a
    single manifest YAML path (``manifest_path=...``), or no path at all
    (auto-discovers manifests under ``.deployments/flows/``), the
    executor iterates flow entries in topological order, runs structure
    DDL interleaved with flow backfills, records deployment metadata,
    and cascade-skips dependents on failure.

    The executor is intentionally **planning-agnostic** : it never calls
    the planner. Producing the manifest is the orchestrator's
    responsibility (see ``FlowDeployExecuteTask``).
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(
            name="plan_only",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="manifest_path",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="no_backfill",
            mandatory=False,
        ),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        manifest: DeployManifest | None = None,
        manifest_path: str | None = None,
        metadata_manager: FlowDeployMetadataManager | None = None,
        no_backfill: bool = False,
        plan_only: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if manifest is not None and manifest_path is not None:
            raise ValueError(
                "FlowDeployExecutor accepts either an in-memory `manifest` "
                "or a `manifest_path`, not both.",
            )
        self._manifest = manifest
        self._manifest_path = manifest_path
        self._metadata_manager = metadata_manager
        self._no_backfill = no_backfill
        self._plan_only = plan_only

        metadata_backend_connector_name = (
            self.execution_context.project.metadata_backend_connector
        )
        if metadata_backend_connector_name is None:
            raise ValueError(
                "metadata_backend_connector must be set in the project "
                "configuration to use FlowDeployExecutor.",
            )

        self._metadata_backend_connector: SQLDataConnector[Any] = cast(
            SQLDataConnector[Any],
            self.execution_context.get_data_connector(
                metadata_backend_connector_name,
                open_connection=True,
            ),
        )
        if self._metadata_manager is None:
            self._metadata_manager = FlowDeployMetadataManager(
                connector=self._metadata_backend_connector,
            )

        metadata_schema = self._metadata_backend_connector.get_active_schema()
        if metadata_schema is None:
            raise ValueError(
                "metadata_backend_connector must have a schema configured. "
                "Set 'schema_name' on the connection credentials.",
            )
        self._metadata_schema = metadata_schema
        self._structure_metadata_manager = StructureMetadataBackendManager(
            metadata_connector=self._metadata_backend_connector,
        )
        self.execution_context.load_entities()

    def run(
        self,
        **kwargs: Any,
    ) -> list[FlowDeployResult]:
        """Apply the configured manifest(s).

        Resolution order:

        1. If an in-memory ``manifest`` was injected, apply it directly.
        2. Else, if ``manifest_path`` was provided, load and apply that
           single file.
        3. Otherwise, auto-discover manifests in ``.deployments/flows/``
           and apply each in sorted order, stopping on the first failure.
        """
        if self._manifest is not None:
            result = self._execute_deployment(
                manifest=self._manifest,
                manifest_path=None,
            )
            return [result]

        if self._manifest_path is not None:
            manifest_paths = [self._manifest_path]
        else:
            from nld.flow.deploy.flow_manifest_discovery import discover_manifests

            entities_root = self.execution_context.project.entities_root_folder_path
            manifest_paths = discover_manifests(
                entities_root_folder_path=entities_root,
            )

        if not manifest_paths:
            self.log_info("No deployment manifests found in .deployments/flows/")
            return []

        self.log_info(f"Found {len(manifest_paths)} manifest(s) to process")

        return self._execute_deployments(
            manifest_paths=manifest_paths,
        )

    # ------------------------------------------------------------------
    # Manifest execution
    # ------------------------------------------------------------------

    def _execute_deployment(
        self,
        manifest: DeployManifest,
        manifest_path: str | None = None,
    ) -> FlowDeployResult:
        """Execute a single deployment manifest."""
        registry = self.execution_context.entity_registry

        deployment_id = str(uuid.uuid4())
        manifest_name = (
            os.path.basename(manifest_path) if manifest_path is not None else "unknown"
        )

        result = FlowDeployResult(deployment_id=deployment_id)
        skipped_flow_names: set[str] = set()

        # Insert deployment record at the start
        if (
            self._metadata_manager is not None
            and self._metadata_schema is not None
            and not self._plan_only
        ):
            self._metadata_manager.ensure_metadata_tables(
                metadata_schema=self._metadata_schema,
            )
            self._structure_metadata_manager.ensure_metadata_tables(
                metadata_schema=self._metadata_schema,
            )
            deployment_row = FlowDeploymentRow(
                deployment_id=deployment_id,
                manifest_id=manifest.manifest_id,
                manifest_name=manifest_name,
                started_at=get_current_datetime(),
                flows_total=len(manifest.flows),
            )
            self._metadata_manager.insert_deployment(
                metadata_schema=self._metadata_schema,
                record=deployment_row,
            )

        # --- Build lookup maps from links for interleaved execution
        flow_target_structures = self._build_flow_target_structure_map(
            manifest=manifest,
        )
        structure_entries_by_key = self._build_structure_entry_map(
            manifest=manifest,
        )
        deployed_structures: set[str] = set()
        skipped_structure_keys: set[str] = set()

        # --- Interleaved structure + flow deployment phase
        try:
            for entry in manifest.flows:
                flow_key = self._build_flow_key(
                    namespace=entry.namespace,
                    flow_name=entry.flow_name,
                )

                # Skip unchanged or removed flows
                if entry.action in (
                    FlowDeployAction.UNCHANGED,
                    FlowDeployAction.REMOVED,
                ):
                    result.skipped[flow_key] = f"{entry.action} (no action needed)"
                    self._record_flow_change(
                        deployment_id=deployment_id,
                        entry=entry,
                        backfill_status="skipped",
                    )
                    continue

                # Skip flows whose predecessors failed
                if flow_key in skipped_flow_names:
                    result.skipped[flow_key] = "predecessor failed"
                    self._record_flow_change(
                        deployment_id=deployment_id,
                        entry=entry,
                        backfill_status="skipped",
                        error_message="predecessor failed",
                    )
                    continue

                # Deploy target structures before executing this flow
                structure_failed = False
                for structure_key in flow_target_structures.get(flow_key, set()):
                    if structure_key in deployed_structures:
                        continue
                    if structure_key in skipped_structure_keys:
                        structure_failed = True
                        continue
                    structure_entry = structure_entries_by_key.get(structure_key)
                    if structure_entry is None:
                        continue
                    try:
                        structure_dep_id = self._execute_structure_from_entry(
                            structure_entry=structure_entry,
                        )
                        deployed_structures.add(structure_key)
                        result.structures_deployed.append(structure_key)
                        if structure_dep_id is not None:
                            self._record_structure_change(
                                deployment_id=deployment_id,
                                structure_deployment_id=structure_dep_id,
                            )
                    except Exception as exc:
                        error_msg = str(exc)
                        self.log_error(
                            f"Structure '{structure_entry.structure_name}' "
                            f"deployment failed: {error_msg}"
                        )
                        skipped_structure_keys.add(structure_key)
                        result.structures_failed[structure_key] = error_msg
                        structure_failed = True

                if structure_failed:
                    for sk in flow_target_structures.get(flow_key, set()):
                        if (
                            sk in skipped_structure_keys
                            and sk not in result.structures_failed
                        ):
                            result.structures_skipped[sk] = (
                                "predecessor structure failed"
                            )
                    result.skipped[flow_key] = "target structure deployment failed"
                    self._record_flow_change(
                        deployment_id=deployment_id,
                        entry=entry,
                        backfill_status="skipped",
                        error_message="target structure deployment failed",
                    )
                    dependents = self._get_dependent_flow_keys(
                        failed_entry=entry,
                        manifest=manifest,
                    )
                    skipped_flow_names.update(dependents)
                    continue

                try:
                    flow_history_id = self._execute_single_flow(
                        entry=entry,
                        registry=registry,
                        result=result,
                        deployment_id=deployment_id,
                    )
                    self._record_flow_change(
                        deployment_id=deployment_id,
                        entry=entry,
                        backfill_status="success",
                        flow_history_id=flow_history_id,
                    )
                except Exception as exc:
                    error_msg = str(exc)
                    result.failed[flow_key] = error_msg
                    self.log_error(f"Flow '{flow_key}' deployment failed: {error_msg}")

                    self._record_flow_change(
                        deployment_id=deployment_id,
                        entry=entry,
                        backfill_status="failed",
                        error_message=error_msg,
                    )

                    # Cascade-skip dependents
                    dependents = self._get_dependent_flow_keys(
                        failed_entry=entry,
                        manifest=manifest,
                    )
                    skipped_flow_names.update(dependents)

            # Deploy structures not reached by the flow loop
            for structure_entry in manifest.structures:
                structure_key = self._build_structure_key(
                    namespace=structure_entry.namespace,
                    structure_name=structure_entry.structure_name,
                )
                if structure_key in deployed_structures:
                    continue
                if structure_key in skipped_structure_keys:
                    continue
                try:
                    structure_dep_id = self._execute_structure_from_entry(
                        structure_entry=structure_entry,
                    )
                    deployed_structures.add(structure_key)
                    if structure_dep_id is not None:
                        self._record_structure_change(
                            deployment_id=deployment_id,
                            structure_deployment_id=structure_dep_id,
                        )
                except Exception as exc:
                    error_msg = str(exc)
                    self.log_error(
                        f"Structure '{structure_entry.structure_name}' "
                        f"deployment failed: {error_msg}"
                    )
                    skipped_structure_keys.add(structure_key)
        finally:
            # Always update deployment record, even when an unexpected
            # error interrupts the loop.
            if (
                self._metadata_manager is not None
                and self._metadata_schema is not None
                and not self._plan_only
            ):
                status = self._compute_deployment_status(result=result)
                self._metadata_manager.update_deployment_status(
                    metadata_schema=self._metadata_schema,
                    deployment_id=deployment_id,
                    status=status,
                    completed_at=get_current_datetime(),
                    flows_in_error=result.failed_count,
                    flows_in_success=result.succeeded_count,
                    flows_skipped=result.skipped_count,
                    structures_in_error=result.structures_failed_count,
                    structures_in_success=result.structures_succeeded_count,
                    structures_skipped=result.structures_skipped_count,
                    structures_total=result.structures_total,
                )

        return result

    def _execute_deployments(
        self,
        manifest_paths: list[str],
    ) -> list[FlowDeployResult]:
        """Execute multiple manifests in order.

        Stops on the first manifest that has any failures.
        Skips manifests whose manifest_id is already in the
        deployment table.
        """
        results: list[FlowDeployResult] = []

        for manifest_path in manifest_paths:
            manifest_data = load_yaml_file_into_dict(
                file_path=manifest_path,
            )
            manifest = DeployManifest(**manifest_data)

            # Check if already deployed by manifest_id
            if (
                self._metadata_manager is not None
                and self._metadata_schema is not None
                and not self._plan_only
            ):
                self._metadata_manager.ensure_metadata_tables(
                    metadata_schema=self._metadata_schema,
                )
                if self._metadata_manager.is_manifest_already_deployed(
                    metadata_schema=self._metadata_schema,
                    manifest_id=manifest.manifest_id,
                ):
                    self.log_info(
                        f"Manifest '{os.path.basename(manifest_path)}' "
                        f"already deployed, skipping"
                    )
                    continue

            self.log_info(f"Executing manifest: {os.path.basename(manifest_path)}")
            result = self._execute_deployment(
                manifest=manifest,
                manifest_path=manifest_path,
            )
            results.append(result)

            # Stop on failure
            if result.failed_count > 0:
                self.log_error(
                    f"Manifest '{os.path.basename(manifest_path)}' "
                    f"had {result.failed_count} failure(s), "
                    f"stopping batch execution"
                )
                break

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute_single_flow(
        self,
        entry: FlowDeployEntry,
        registry: Any,
        result: FlowDeployResult,
        deployment_id: str,
    ) -> str | None:
        """Execute backfill for one flow entry.

        Returns:
            The flow history deployment_id, or None if metadata
            recording is disabled.
        """
        flow_key = self._build_flow_key(
            namespace=entry.namespace,
            flow_name=entry.flow_name,
        )

        # --- Flow execution phase
        if (
            entry.backfill_strategy != BackfillStrategy.NONE
            and not self._no_backfill
            and not self._plan_only
        ):
            flow_exec_info = self._execute_flow_backfill(
                entry=entry,
                registry=registry,
            )
            if flow_exec_info is not None:
                result.flow_results.append(flow_exec_info)

        # --- Metadata recording
        flow_history_id: str | None = None
        if (
            self._metadata_manager is not None
            and self._metadata_schema is not None
            and not self._plan_only
        ):
            flow_history_id = self._record_deployment_metadata(
                entry=entry,
                manifest_deployment_id=deployment_id,
            )

        result.deployed.append(entry)
        self.log_info(f"Flow '{flow_key}' deployed successfully")

        return flow_history_id

    def _execute_structure_from_entry(
        self,
        structure_entry: StructureDeployEntry,
    ) -> str | None:
        """Deploy a structure from its manifest entry.

        Returns the structure deployment_id if deployed, None otherwise.
        """
        if structure_entry.action == StructureDeployAction.NONE:
            return None

        structure_config = self.execution_context.project.structure_config
        mapping = structure_config.get_mapping(
            namespace=structure_entry.namespace,
        )
        target_connector = cast(
            SQLDataConnector[Any],
            self.execution_context.get_data_connector(
                mapping.default_connection_name,
                open_connection=True,
            ),
        )

        registry = self.execution_context.entity_registry
        namespaced_structure = registry.get_structure(
            entity_key=structure_entry.structure_name,
            namespace=structure_entry.namespace,
        )

        variables = resolve_variables(
            project_variables=self.execution_context.project.variables,
        )
        deploy_manager = StructureDeployManager(
            structure_connector=target_connector,
            deploy_schema=mapping.schema_name,
            metadata_backend_connector=self._metadata_backend_connector,
            metadata_schema=self._metadata_schema,
            variables=variables,
        )

        if self._plan_only:
            change_set = deploy_manager.compute_change_set(
                structure=namespaced_structure.model,
            )
            for stmt in change_set.statements:
                self.log_info(f"[PLAN] Would execute: {stmt.sql}")
            return None

        deploy_result = deploy_manager.deploy(
            namespaced_structure=namespaced_structure,
        )
        if deploy_result.deployed:
            for stmt in deploy_result.statements:
                self.log_debug(f"Executed DDL: {stmt.sql}")

        structure_key = self._build_structure_key(
            namespace=structure_entry.namespace,
            structure_name=structure_entry.structure_name,
        )
        self.log_info(
            f"Structure '{structure_key}' deployed successfully "
            f"[{structure_entry.action}]",
        )

        return deploy_result.deployment_id

    def _execute_flow_backfill(
        self,
        entry: FlowDeployEntry,
        registry: Any,
    ) -> FlowExecutionInfo | None:
        """Execute a flow backfill based on the entry's strategy."""
        if entry.backfill_strategy == BackfillStrategy.NONE:
            return None

        namespaced_flow = registry.get_data_flow_definition(
            entity_key=entry.flow_name,
            namespace=entry.namespace,
        )

        if entry.backfill_strategy == BackfillStrategy.FULL:
            return self._execute_full_backfill(
                namespaced_flow=namespaced_flow,
            )

        if entry.backfill_strategy == BackfillStrategy.COLUMN:
            return self._execute_column_backfill(
                namespaced_flow=namespaced_flow,
                columns=entry.backfill_columns,
            )

        return None

    def _execute_full_backfill(
        self,
        namespaced_flow: NamespacedDataFlowDefinition,
    ) -> FlowExecutionInfo:
        """Execute a full flow backfill via DataFlowExecutor."""
        executor = DataFlowExecutor(
            namespaced_data_flow_definition=namespaced_flow,
        )
        data_flow_task = executor.init_data_flow_task(
            connections_should_be_opened=True,
        )
        return executor.execute_data_flow_task(data_flow_task=data_flow_task)

    def _execute_column_backfill(
        self,
        namespaced_flow: NamespacedDataFlowDefinition,
        columns: list[str],
    ) -> FlowExecutionInfo | None:
        """Execute a column-specific backfill.

        Falls back to full backfill if no primary key is found on the
        target structure.
        """
        if not columns:
            self.log_warn(
                "Column backfill requested but no columns specified. "
                "Falling back to full backfill."
            )
            return self._execute_full_backfill(
                namespaced_flow=namespaced_flow,
            )

        # Column backfill requires PK on target structure.
        # Fall back to full if we cannot determine PK.
        flow_def = namespaced_flow.model
        if flow_def.target_structure is None:
            self.log_warn(
                "Column backfill requires target_structure. "
                "Falling back to full backfill."
            )
            return self._execute_full_backfill(
                namespaced_flow=namespaced_flow,
            )

        # For now, fall back to full backfill since column-level
        # UPDATE requires connector-specific SQL generation.
        self.log_info(
            f"Column backfill for columns {columns}. "
            f"Executing full backfill as fallback."
        )
        return self._execute_full_backfill(
            namespaced_flow=namespaced_flow,
        )

    def _record_deployment_metadata(
        self,
        entry: FlowDeployEntry,
        manifest_deployment_id: str,
    ) -> str | None:
        """Write metadata and history records for a deployed flow.

        Returns:
            The flow history deployment_id, or None if metadata
            recording is disabled.
        """
        if self._metadata_manager is None or self._metadata_schema is None:
            return None

        deployment_id = str(uuid.uuid4())
        now = get_current_datetime()

        # Get previous deployment ID
        previous_deployment_id = self._metadata_manager.get_previous_deployment_id(
            metadata_schema=self._metadata_schema,
            flow_name=entry.flow_name,
            namespace=entry.namespace,
        )

        # Compute hashes from the current flow definition
        entities_root = self.execution_context.project.entities_root_folder_path
        entity_path = self.execution_context.project.entity_path
        additional_flow_task_types = (
            self.execution_context.project.flow_config.additional_flow_task_types
        )
        additional_task_paths = (
            self.execution_context.project.flows_python_additional_paths
        )
        registry = self.execution_context.entity_registry

        namespaced_flow = registry.get_data_flow_definition(
            entity_key=entry.flow_name,
            namespace=entry.namespace,
        )

        from nld.flow.deploy.flow_definition_hash import (
            build_flow_yaml_snapshot_json,
            compute_flow_definition_hash,
            compute_flow_python_hash,
            compute_flow_sql_hash,
            compute_flow_yaml_hash,
        )
        from nld.structure.deploy import compute_structure_hash

        flow_def = namespaced_flow.model
        yaml_hash = compute_flow_yaml_hash(flow_definition=flow_def)
        sql_hash = compute_flow_sql_hash(
            entities_root_folder_path=entities_root,
            namespace=entry.namespace,
            flow_name=entry.flow_name,
        )
        python_hash = compute_flow_python_hash(
            flow_definition=flow_def,
            namespace=entry.namespace,
            entity_path=entity_path,
            additional_task_paths=additional_task_paths,
            additional_flow_task_types=additional_flow_task_types,
        )
        definition_hash = compute_flow_definition_hash(
            flow_definition=flow_def,
            entities_root_folder_path=entities_root,
            namespace=entry.namespace,
            entity_path=entity_path,
            additional_task_paths=additional_task_paths,
            additional_flow_task_types=additional_flow_task_types,
        )

        # Compute target structure hash
        target_structure_hash = None
        if flow_def.target_structure is not None:
            try:
                resolved_structure = flow_def.resolve_target_structure()
                target_structure_hash = compute_structure_hash(
                    structure=resolved_structure,
                )
            except Exception:
                pass

        # Compute predecessor hashes
        predecessor_hashes: dict[str, str] | None = None
        if flow_def.predecessors:
            from nld.service.nld_entity_registry import EntityTypeNames

            pred_hashes: dict[str, str] = {}
            for _pred_name, predecessor in flow_def.predecessors.items():
                try:
                    resolved = predecessor.full_path.resolve(
                        entity_type=EntityTypeNames.STRUCTURE,
                    )
                    pred_hashes[str(predecessor.full_path)] = compute_structure_hash(
                        structure=resolved,
                    )
                except Exception:
                    pass
            if pred_hashes:
                predecessor_hashes = pred_hashes

        # Compute flow YAML snapshot
        flow_yaml_snapshot = build_flow_yaml_snapshot_json(
            flow_definition=flow_def,
        )

        metadata_row = FlowDeployMetadataRow(
            namespace=entry.namespace,
            flow_name=entry.flow_name,
            deployment_id=deployment_id,
            deployed_at=now,
            flow_definition_hash=definition_hash,
            flow_yaml_hash=yaml_hash,
            flow_sql_hash=sql_hash,
            flow_python_hash=python_hash,
            flow_yaml_snapshot=flow_yaml_snapshot,
            last_deployment_id=manifest_deployment_id,
            predecessor_hashes=predecessor_hashes,
            target_structure_hash=target_structure_hash,
        )

        history_row = FlowDeployHistoryRow(
            deployment_id=deployment_id,
            namespace=entry.namespace,
            flow_name=entry.flow_name,
            deployed_at=now,
            flow_definition_hash=definition_hash,
            flow_yaml_hash=yaml_hash,
            flow_sql_hash=sql_hash,
            flow_python_hash=python_hash,
            flow_yaml_snapshot=flow_yaml_snapshot,
            target_structure_hash=target_structure_hash,
            diff_action=str(entry.action),
            backfill_strategy=str(entry.backfill_strategy),
            manifest_deployment_id=manifest_deployment_id,
            predecessor_hashes=predecessor_hashes,
            previous_deployment_id=previous_deployment_id,
        )

        self._metadata_manager.upsert_current_state(
            metadata_schema=self._metadata_schema,
            record=metadata_row,
        )
        self._metadata_manager.write_history_record(
            metadata_schema=self._metadata_schema,
            record=history_row,
        )

        return deployment_id

    def _record_flow_change(
        self,
        deployment_id: str,
        entry: FlowDeployEntry,
        backfill_status: str,
        error_message: str | None = None,
        flow_history_id: str | None = None,
    ) -> None:
        """Record a flow change in the deployment flow change table."""
        if (
            self._metadata_manager is None
            or self._metadata_schema is None
            or self._plan_only
        ):
            return

        record = FlowDeploymentFlowChangeRow(
            deployment_id=deployment_id,
            flow_name=entry.flow_name,
            namespace=entry.namespace,
            backfill_status=backfill_status,
            changed_at=get_current_datetime(),
            error_message=error_message,
            flow_history_id=flow_history_id,
        )
        self._metadata_manager.insert_flow_change(
            metadata_schema=self._metadata_schema,
            record=record,
        )

    def _record_structure_change(
        self,
        deployment_id: str,
        structure_deployment_id: str,
    ) -> None:
        """Link a flow deployment to a structure deployment."""
        if (
            self._metadata_manager is None
            or self._metadata_schema is None
            or self._plan_only
        ):
            return

        record = FlowDeploymentStructureChangeRow(
            deployment_id=deployment_id,
            structure_deployment_id=structure_deployment_id,
            changed_at=get_current_datetime(),
        )
        self._metadata_manager.insert_structure_change(
            metadata_schema=self._metadata_schema,
            record=record,
        )

    def _compute_deployment_status(
        self,
        result: FlowDeployResult,
    ) -> str:
        """Compute the overall deployment status from results."""
        if result.failed_count > 0 and result.succeeded_count > 0:
            return "partial"
        if result.failed_count > 0:
            return "failed"
        return "success"

    def _get_dependent_flow_keys(
        self,
        failed_entry: FlowDeployEntry,
        manifest: DeployManifest,
    ) -> set[str]:
        """Find all flow keys that transitively depend on the failed flow.

        Uses the manifest's dependency links to traverse the graph
        and identify flows that should be skipped when a predecessor
        fails.
        """
        failed_key = self._build_flow_key(
            namespace=failed_entry.namespace,
            flow_name=failed_entry.flow_name,
        )

        # Build adjacency map from links
        adjacency: dict[str, set[str]] = {}
        for link in manifest.links:
            source_key = f"{link.source_type}.{link.source_id}"
            target_key = f"{link.target_type}.{link.target_id}"
            if source_key not in adjacency:
                adjacency[source_key] = set()
            adjacency[source_key].add(target_key)

        # BFS from the failed flow to find all transitive dependents
        failed_node = f"flow.{failed_key}"
        dependents: set[str] = set()
        frontier = {failed_node}

        while frontier:
            current = frontier.pop()
            for downstream in adjacency.get(current, set()):
                if downstream not in dependents and downstream != failed_node:
                    dependents.add(downstream)
                    frontier.add(downstream)

        # Extract flow keys from dependent node IDs
        flow_keys: set[str] = set()
        for dep in dependents:
            if dep.startswith("flow."):
                flow_keys.add(dep[len("flow.") :])

        return flow_keys

    def _build_flow_key(
        self,
        namespace: str,
        flow_name: str,
    ) -> str:
        """Build a unique key from namespace and flow name."""
        if NldNamespace(namespace).is_root:
            return flow_name
        return f"{namespace}.{flow_name}"

    def _build_structure_key(
        self,
        namespace: str,
        structure_name: str,
    ) -> str:
        """Build a unique key from namespace and structure name."""
        if NldNamespace(namespace).is_root:
            return structure_name
        return f"{namespace}.{structure_name}"

    def _build_flow_target_structure_map(
        self,
        manifest: DeployManifest,
    ) -> dict[str, set[str]]:
        """Build a mapping from flow keys to their target structure keys.

        Uses the manifest links to identify which structures each
        flow writes to, so structures can be deployed right before
        the flow that targets them.
        """
        flow_targets: dict[str, set[str]] = {}
        for link in manifest.links:
            if link.source_type == "flow" and link.target_type == "structure":
                flow_targets.setdefault(link.source_id, set()).add(
                    link.target_id,
                )
        return flow_targets

    def _build_structure_entry_map(
        self,
        manifest: DeployManifest,
    ) -> dict[str, StructureDeployEntry]:
        """Build a mapping from structure keys to their manifest entries.

        Keys use the ``namespace.structure_name`` format which
        matches the link ``target_id`` produced by the planner.
        """
        entries: dict[str, StructureDeployEntry] = {}
        for structure_entry in manifest.structures:
            key = self._build_structure_key(
                namespace=structure_entry.namespace,
                structure_name=structure_entry.structure_name,
            )
            entries[key] = structure_entry
        return entries
