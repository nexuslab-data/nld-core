import datetime
from typing import Any

from nld.connector.base.connector import SQLDataConnector
from nld.flow.deploy.flow_deploy_metadata_models import (
    FlowDeployHistoryRow,
    FlowDeploymentFlowChangeRow,
    FlowDeploymentRow,
    FlowDeploymentStructureChangeRow,
    FlowDeployMetadataRow,
)
from nld.logging.logger import NldLoggable

NLD_FLOW_DEPLOYMENT_FLOW_CHANGE_TABLE = "_nld_flow_deployment_flow_change"
NLD_FLOW_DEPLOYMENT_STRUCTURE_CHANGE_TABLE = "_nld_flow_deployment_structure_change"
NLD_FLOW_DEPLOYMENT_TABLE = "_nld_flow_deployment"
NLD_FLOW_HISTORY_TABLE = "_nld_flow_history"
NLD_FLOW_STATE_TABLE = "_nld_flow_state"


class FlowDeployMetadataManager(NldLoggable):
    """Manages the flow deployment metadata tables.

    Provides CRUD operations for five metadata tables:
    - ``_nld_flow_deployment``: one row per deploy run
    - ``_nld_flow_deployment_flow_change``: one row per flow change
    - ``_nld_flow_deployment_structure_change``: one row per structure change
    - ``_nld_flow_state``: current state per flow (upserted)
    - ``_nld_flow_history``: append-only log per flow event
    """

    def __init__(
        self,
        connector: SQLDataConnector[Any],
    ) -> None:
        super().__init__()
        self._connector = connector
        self._model_manager = connector.get_model_manager()

    # ------------------------------------------------------------------
    # Table lifecycle
    # ------------------------------------------------------------------

    def ensure_metadata_tables(
        self,
        metadata_schema: str,
    ) -> None:
        """Create all five metadata tables if they do not exist."""
        self._model_manager.create_table(
            model_class=FlowDeploymentRow,
            schema_name=metadata_schema,
            table_name=NLD_FLOW_DEPLOYMENT_TABLE,
            track_timestamps=True,
        )
        self._model_manager.create_table(
            model_class=FlowDeploymentFlowChangeRow,
            schema_name=metadata_schema,
            table_name=NLD_FLOW_DEPLOYMENT_FLOW_CHANGE_TABLE,
            track_timestamps=True,
        )
        self._model_manager.create_table(
            model_class=FlowDeployHistoryRow,
            schema_name=metadata_schema,
            table_name=NLD_FLOW_HISTORY_TABLE,
            track_timestamps=True,
        )
        self._model_manager.create_table(
            model_class=FlowDeployMetadataRow,
            schema_name=metadata_schema,
            table_name=NLD_FLOW_STATE_TABLE,
            track_timestamps=True,
        )
        self._model_manager.create_table(
            model_class=FlowDeploymentStructureChangeRow,
            schema_name=metadata_schema,
            table_name=NLD_FLOW_DEPLOYMENT_STRUCTURE_CHANGE_TABLE,
            track_timestamps=True,
        )

    # ------------------------------------------------------------------
    # Deployment-level operations
    # ------------------------------------------------------------------

    def insert_deployment(
        self,
        metadata_schema: str,
        record: FlowDeploymentRow,
    ) -> None:
        """Insert a new deployment record."""
        self._model_manager.insert_model(
            model=record,
            schema_name=metadata_schema,
            table_name=NLD_FLOW_DEPLOYMENT_TABLE,
            track_timestamps=True,
        )

    def update_deployment_status(
        self,
        metadata_schema: str,
        deployment_id: str,
        status: str,
        completed_at: datetime.datetime,
        flows_in_error: int,
        flows_in_success: int,
        flows_skipped: int,
        structures_in_error: int = 0,
        structures_in_success: int = 0,
        structures_skipped: int = 0,
        structures_total: int = 0,
    ) -> None:
        """Update the status and counts of a deployment after execution."""
        updated_row = FlowDeploymentRow(
            changeset_id="",
            completed_at=completed_at,
            deployment_id=deployment_id,
            flows_in_error=flows_in_error,
            flows_in_success=flows_in_success,
            flows_skipped=flows_skipped,
            started_at=completed_at,
            status=status,
            structures_in_error=structures_in_error,
            structures_in_success=structures_in_success,
            structures_skipped=structures_skipped,
            structures_total=structures_total,
        )
        self._model_manager.update_model(
            model=updated_row,
            schema_name=metadata_schema,
            table_name=NLD_FLOW_DEPLOYMENT_TABLE,
            exclude_fields={"changeset_id"},
            track_timestamps=True,
        )

    # ------------------------------------------------------------------
    # Flow change operations
    # ------------------------------------------------------------------

    def insert_flow_change(
        self,
        metadata_schema: str,
        record: FlowDeploymentFlowChangeRow,
    ) -> None:
        """Insert a flow change record for a deployment."""
        self._model_manager.insert_model(
            model=record,
            schema_name=metadata_schema,
            table_name=NLD_FLOW_DEPLOYMENT_FLOW_CHANGE_TABLE,
            track_timestamps=True,
        )

    # ------------------------------------------------------------------
    # Structure change operations
    # ------------------------------------------------------------------

    def insert_structure_change(
        self,
        metadata_schema: str,
        record: FlowDeploymentStructureChangeRow,
    ) -> None:
        """Insert a structure change record for a deployment."""
        self._model_manager.insert_model(
            model=record,
            schema_name=metadata_schema,
            table_name=NLD_FLOW_DEPLOYMENT_STRUCTURE_CHANGE_TABLE,
            track_timestamps=True,
        )

    # ------------------------------------------------------------------
    # Per-flow metadata operations (existing, updated)
    # ------------------------------------------------------------------

    def get_previous_hashes(
        self,
        metadata_schema: str,
        flow_name: str,
        namespace: str,
    ) -> tuple[str | None, str | None, str | None, str | None]:
        """Return the previous (definition, yaml, sql, python) hashes.

        All values are None when no previous deployment exists.
        """
        row = self._read_metadata_row(
            metadata_schema=metadata_schema,
            flow_name=flow_name,
            namespace=namespace,
        )
        if row is None:
            return None, None, None, None
        return (
            row.flow_definition_hash,
            row.flow_yaml_hash,
            row.flow_sql_hash,
            row.flow_python_hash,
        )

    def read_state_row(
        self,
        metadata_schema: str,
        flow_name: str,
        namespace: str,
    ) -> FlowDeployMetadataRow | None:
        """Read the current recorded state row of a flow."""
        return self._read_metadata_row(
            metadata_schema=metadata_schema,
            flow_name=flow_name,
            namespace=namespace,
        )

    def get_previous_deployment_id(
        self,
        metadata_schema: str,
        flow_name: str,
        namespace: str,
    ) -> str | None:
        """Return the deployment_id of the last deployment, or None."""
        row = self._read_metadata_row(
            metadata_schema=metadata_schema,
            flow_name=flow_name,
            namespace=namespace,
        )
        if row is None:
            return None
        return row.deployment_id

    def upsert_current_state(
        self,
        metadata_schema: str,
        record: FlowDeployMetadataRow,
    ) -> None:
        """Insert or update the current deployment state for a flow."""
        self._model_manager.upsert_model(
            model=record,
            schema_name=metadata_schema,
            table_name=NLD_FLOW_STATE_TABLE,
            track_timestamps=True,
        )

    def delete_state_row(
        self,
        metadata_schema: str,
        namespace: str,
        flow_name: str,
    ) -> None:
        """Delete the current state row of a flow.

        Used by rename_flow directives: the renamed flow records a
        fresh row under its new name and the old row must not read
        as a REMOVED flow afterwards.
        """
        self._connector.delete_from(
            table_path=f"{metadata_schema}.{NLD_FLOW_STATE_TABLE}",
            where_conditions={
                "namespace": namespace,
                "flow_name": flow_name,
            },
        )

    def write_history_record(
        self,
        metadata_schema: str,
        record: FlowDeployHistoryRow,
    ) -> None:
        """Append an immutable history record for a deployment event."""
        self._model_manager.insert_model(
            model=record,
            schema_name=metadata_schema,
            table_name=NLD_FLOW_HISTORY_TABLE,
            track_timestamps=True,
        )

    def get_all_deployed_flows(
        self,
        metadata_schema: str,
        namespace: str | None = None,
    ) -> dict[str, FlowDeployMetadataRow]:
        """Return all currently deployed flows, optionally filtered by namespace.

        When a namespace is provided, returns flows whose namespace matches
        exactly or starts with the namespace followed by a dot. This matches
        the hierarchical namespace behaviour of the entity registry.

        Returns:
            Dict keyed by ``namespace.flow_name`` (or just ``flow_name``
            for root namespace).
        """
        models = self._model_manager.read_models(
            model_class=FlowDeployMetadataRow,
            schema_name=metadata_schema,
            table_name=NLD_FLOW_STATE_TABLE,
        )

        rows: dict[str, FlowDeployMetadataRow] = {}
        for model in models:
            row: FlowDeployMetadataRow = model  # type: ignore[assignment]

            if namespace is not None and not self._namespace_matches(
                row_namespace=row.namespace,
                filter_namespace=namespace,
            ):
                continue

            key = (
                f"{row.namespace}.{row.flow_name}"
                if row.namespace != "."
                else row.flow_name
            )
            rows[key] = row

        return rows

    @staticmethod
    def _namespace_matches(
        row_namespace: str,
        filter_namespace: str,
    ) -> bool:
        """Check if a row namespace belongs to the filter namespace hierarchy."""
        return row_namespace == filter_namespace or row_namespace.startswith(
            f"{filter_namespace}."
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_metadata_row(
        self,
        metadata_schema: str,
        flow_name: str,
        namespace: str,
    ) -> FlowDeployMetadataRow | None:
        """Read a single state row by primary key."""
        result = self._model_manager.read_model(
            model_class=FlowDeployMetadataRow,
            schema_name=metadata_schema,
            table_name=NLD_FLOW_STATE_TABLE,
            where_conditions={
                "namespace": namespace,
                "flow_name": flow_name,
            },
        )
        if result is None:
            return None
        return result  # type: ignore[return-value]
