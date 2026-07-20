from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from nld.connector.base.connector import SQLDataConnector
from nld.exceptions import NldRuntimeException
from nld.structure.deploy.structure_metadata_models import (
    StructureDeployRunRow,
    StructureHistoryRow,
    StructureMetadataRow,
)
from nld.structure.deploy.structure_schema_history import (
    StructureSchemaHistoryRecord,
)

NLD_STRUCTURE_STATE_TABLE = "_nld_structure_state"
NLD_STRUCTURE_HISTORY_TABLE = "_nld_structure_history"
NLD_STRUCTURE_DEPLOY_RUN_TABLE = "_nld_structure_deployment"


class StructureMetadataBackendManager:
    """Persists schema history records and current schema metadata.

    Manages the metadata tables in the target connector and provides
    methods to insert history records and upsert the current schema.
    Uses NldBaseModelManager for all data operations.
    """

    def __init__(
        self,
        metadata_connector: SQLDataConnector[Any],
    ) -> None:
        self._connector = metadata_connector
        self._model_manager = metadata_connector.get_model_manager()

    def ensure_metadata_tables(
        self,
        metadata_schema: str,
    ) -> None:
        """Verify the metadata schema exists and create tables if needed."""
        self._verify_schema_exists(schema=metadata_schema)

        state_table_exists = self._table_exists(
            schema=metadata_schema,
            table=NLD_STRUCTURE_STATE_TABLE,
        )
        if not state_table_exists:
            self._model_manager.create_table(
                model_class=StructureMetadataRow,
                schema_name=metadata_schema,
                table_name=NLD_STRUCTURE_STATE_TABLE,
                table_exists="skip",
                track_timestamps=True,
            )

        history_table_exists = self._table_exists(
            schema=metadata_schema,
            table=NLD_STRUCTURE_HISTORY_TABLE,
        )
        if not history_table_exists:
            self._model_manager.create_table(
                model_class=StructureHistoryRow,
                schema_name=metadata_schema,
                table_name=NLD_STRUCTURE_HISTORY_TABLE,
                table_exists="skip",
                track_timestamps=True,
            )

    def ensure_deploy_run_table(
        self,
        metadata_schema: str,
    ) -> None:
        """Create the structure-deploy run table when missing.

        Ensured only by the ``nld structure deploy`` path — the flow
        path records its runs in its own deployment table.
        """
        run_table_exists = self._table_exists(
            schema=metadata_schema,
            table=NLD_STRUCTURE_DEPLOY_RUN_TABLE,
        )
        if not run_table_exists:
            self._model_manager.create_table(
                model_class=StructureDeployRunRow,
                schema_name=metadata_schema,
                table_name=NLD_STRUCTURE_DEPLOY_RUN_TABLE,
                table_exists="skip",
                track_timestamps=True,
            )

    def insert_deploy_run(
        self,
        metadata_schema: str,
        row: StructureDeployRunRow,
    ) -> None:
        """Insert the run-level record at the start of a deploy run."""
        self._model_manager.insert_model(
            model=row,
            schema_name=metadata_schema,
            table_name=NLD_STRUCTURE_DEPLOY_RUN_TABLE,
            track_timestamps=True,
        )

    def update_deploy_run(
        self,
        metadata_schema: str,
        row: StructureDeployRunRow,
    ) -> None:
        """Write the run's final status and counters."""
        self._model_manager.upsert_model(
            model=row,
            schema_name=metadata_schema,
            table_name=NLD_STRUCTURE_DEPLOY_RUN_TABLE,
            conflict_fields=["deployment_id"],
            track_timestamps=True,
        )

    def write_history_record(
        self,
        metadata_schema: str,
        record: StructureSchemaHistoryRecord,
    ) -> None:
        """Insert a deployment event into the schema history table."""
        row = StructureHistoryRow.from_history_record(record=record)
        self._model_manager.insert_model(
            model=row,
            schema_name=metadata_schema,
            table_name=NLD_STRUCTURE_HISTORY_TABLE,
            track_timestamps=True,
        )

    def upsert_current_schema(
        self,
        metadata_schema: str,
        record: StructureSchemaHistoryRecord,
    ) -> None:
        """Upsert the current schema snapshot for a structure."""
        row = StructureMetadataRow.from_history_record(record=record)
        self._model_manager.upsert_model(
            model=row,
            schema_name=metadata_schema,
            table_name=NLD_STRUCTURE_STATE_TABLE,
            conflict_fields=["namespace", "structure_name"],
            track_timestamps=True,
        )

    def soft_delete_structure(
        self,
        metadata_schema: str,
        structure_name: str,
        namespace: str,
    ) -> None:
        """Mark a structure as soft-deleted in metadata and record in history."""
        row = self._read_metadata_row(
            metadata_schema=metadata_schema,
            structure_name=structure_name,
            namespace=namespace,
        )
        if row is None:
            msg = (
                f"Structure '{structure_name}' in namespace '{namespace}' "
                f"not found or already deleted."
            )
            raise NldRuntimeException(msg)

        deleted_at = datetime.now(UTC)
        updated_row = row.model_copy(
            update={
                "fl_deleted": True,
                "ts_deleted_at": deleted_at,
            },
        )
        self._model_manager.update_model(
            model=updated_row,
            schema_name=metadata_schema,
            table_name=NLD_STRUCTURE_STATE_TABLE,
            track_timestamps=True,
        )

        history_row = StructureHistoryRow(
            deployment_id=str(uuid.uuid4()),
            uid=row.uid,
            namespace=row.namespace,
            object_path=row.object_path,
            structure_name=row.structure_name,
            deployed_at=deleted_at,
            structure_schema_snapshot=row.structure_schema_snapshot,
            structure_snapshot=row.structure_snapshot,
            structure_schema_hash=row.structure_schema_hash,
            structure_hash=row.structure_hash,
            ddl_applied=False,
            fl_deleted=True,
            ts_deleted_at=deleted_at,
            previous_deployment_id=row.deployment_id,
        )
        self._model_manager.insert_model(
            model=history_row,
            schema_name=metadata_schema,
            table_name=NLD_STRUCTURE_HISTORY_TABLE,
            track_timestamps=True,
        )

    def read_state_row(
        self,
        metadata_schema: str,
        structure_name: str,
        namespace: str,
    ) -> StructureMetadataRow | None:
        """Read the current recorded state row of a structure."""
        return self._read_metadata_row(
            metadata_schema=metadata_schema,
            structure_name=structure_name,
            namespace=namespace,
        )

    def read_all_state_rows(
        self,
        metadata_schema: str,
    ) -> dict[tuple[str, str], StructureMetadataRow]:
        """Read every non-deleted state row in the schema, in one query.

        Keyed by ``(namespace, structure_name)`` — replaces the
        per-structure ``read_state_row`` calls a deploy loop would
        otherwise issue once per call site per structure.
        """
        rows = cast(
            "list[StructureMetadataRow]",
            self._model_manager.read_models(
                model_class=StructureMetadataRow,
                schema_name=metadata_schema,
                table_name=NLD_STRUCTURE_STATE_TABLE,
                where_conditions={"fl_deleted": False},
            ),
        )
        return {(row.namespace, row.structure_name): row for row in rows}

    def _read_metadata_row(
        self,
        metadata_schema: str,
        structure_name: str,
        namespace: str,
    ) -> StructureMetadataRow | None:
        """Read a single metadata row for the given structure and namespace."""
        result = self._model_manager.read_model(
            model_class=StructureMetadataRow,
            schema_name=metadata_schema,
            table_name=NLD_STRUCTURE_STATE_TABLE,
            where_conditions={
                "structure_name": structure_name,
                "namespace": namespace,
                "fl_deleted": False,
            },
        )
        return cast(StructureMetadataRow | None, result)

    def _verify_schema_exists(
        self,
        schema: str,
    ) -> None:
        """Verify the schema exists, raising an error if it does not."""
        if not self._connector.does_schema_exist(schema=schema):
            msg = (
                f"Schema '{schema}' does not exist. "
                f"Create the schema before running structure deploy."
            )
            raise NldRuntimeException(msg)

    def _table_exists(
        self,
        schema: str,
        table: str,
    ) -> bool:
        """Check if a table exists via the standard connector method."""
        return self._connector.does_object_exist(f"{schema}.{table}")
