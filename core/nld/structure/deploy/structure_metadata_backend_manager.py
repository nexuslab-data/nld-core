from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from nld.connector.base.connector import SQLDataConnector
from nld.connector.base.exceptions import SingleValueResultException
from nld.exceptions import NldRuntimeException
from nld.structure.deploy.structure_metadata_models import (
    StructureHistoryRow,
    StructureMetadataRow,
)
from nld.structure.deploy.structure_schema_history import (
    StructureSchemaHistoryRecord,
)

NLD_STRUCTURE_STATE_TABLE = "_nld_structure_state"
NLD_STRUCTURE_HISTORY_TABLE = "_nld_structure_history"


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
        self._ddl_builder = metadata_connector.get_ddl_builder()
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

    def get_previous_deployment_id(
        self,
        metadata_schema: str,
        structure_name: str,
        namespace: str,
    ) -> str | None:
        """Retrieve the latest deployment ID for a structure."""
        row = self._read_metadata_row(
            metadata_schema=metadata_schema,
            structure_name=structure_name,
            namespace=namespace,
        )
        if row is None:
            return None
        return row.deployment_id

    def get_previous_structure_snapshot(
        self,
        metadata_schema: str,
        structure_name: str,
        namespace: str,
    ) -> str | None:
        """Retrieve the latest structure definition snapshot for a structure."""
        row = self._read_metadata_row(
            metadata_schema=metadata_schema,
            structure_name=structure_name,
            namespace=namespace,
        )
        if row is None:
            return None
        return row.structure_snapshot

    def get_previous_hashes(
        self,
        metadata_schema: str,
        structure_name: str,
        namespace: str,
    ) -> tuple[str | None, str | None]:
        """Retrieve the previous structure_schema_hash and structure_hash.

        Returns a tuple of (structure_schema_hash, structure_hash).
        Both are None if no previous deployment exists.
        """
        row = self._read_metadata_row(
            metadata_schema=metadata_schema,
            structure_name=structure_name,
            namespace=namespace,
        )
        if row is None:
            return None, None
        return row.structure_schema_hash, row.structure_hash

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
        sql = self._ddl_builder.build_schema_exists_query(schema=schema)
        result = self._connector.execute_query(sql)
        try:
            schema_exists = bool(result.get_output_data_single_value())
        except SingleValueResultException:
            schema_exists = False
        if not schema_exists:
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
        """Check if a table exists using information_schema."""
        sql = self._ddl_builder.build_exists_query(
            schema=schema,
            table=table,
        )
        result = self._connector.execute_query(sql)
        try:
            return bool(result.get_output_data_single_value())
        except SingleValueResultException:
            return False
