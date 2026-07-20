from __future__ import annotations

from datetime import datetime

from pydantic import Field

from nld.pydantic.base_model import NldBaseModel
from nld.structure.deploy.structure_schema_history import (
    StructureSchemaHistoryRecord,
)


class StructureMetadataRow(NldBaseModel):
    """Flat DB-facing model for the _nld_structure_state table."""

    namespace: str = Field(json_schema_extra={"primary_key": True})
    object_path: str
    structure_name: str = Field(json_schema_extra={"primary_key": True})
    structure_type: str
    deployment_id: str
    uid: str
    deployed_at: datetime
    structure_schema_snapshot: str
    structure_snapshot: str
    structure_schema_hash: str
    structure_hash: str
    record_source: str = "deployment"
    fl_deleted: bool = False
    ts_deleted_at: datetime | None = None

    @classmethod
    def from_history_record(
        cls,
        record: StructureSchemaHistoryRecord,
    ) -> StructureMetadataRow:
        """Build a metadata row from a history record."""
        return cls(
            namespace=record.namespace,
            object_path=record.object_path,
            structure_name=record.structure_name,
            structure_type=record.structure_schema_snapshot.structure_type,
            deployment_id=record.deployment_id,
            uid=record.uid,
            deployed_at=record.deployed_at,
            structure_schema_snapshot=record.schema_snapshot_json(),
            structure_snapshot=record.structure_snapshot,
            structure_schema_hash=record.structure_schema_hash,
            structure_hash=record.structure_hash,
            record_source=record.record_source,
        )


class StructureDeployRunRow(NldBaseModel):
    """Flat DB-facing model for the _nld_structure_deployment table.

    One row per ``nld structure deploy`` run: applied-log and history
    rows carrying the run's deployment_id join back to it for
    incident response.
    """

    deployment_id: str = Field(json_schema_extra={"primary_key": True})
    started_at: datetime
    completed_at: datetime | None = None
    status: str = "running"
    structures_total: int = 0
    structures_in_success: int = 0
    structures_in_error: int = 0
    structures_skipped: int = 0


class StructureHistoryRow(NldBaseModel):
    """Flat DB-facing model for the _nld_structure_history table."""

    deployment_id: str = Field(json_schema_extra={"primary_key": True})
    uid: str
    namespace: str
    object_path: str
    structure_name: str
    deployed_at: datetime
    structure_schema_snapshot: str
    structure_snapshot: str
    structure_schema_hash: str
    structure_hash: str
    diff_summary: str | None = None
    ddl_applied: bool
    ddl_statements: str | None = None
    previous_deployment_id: str | None = None
    record_source: str = "deployment"
    fl_deleted: bool = False
    ts_deleted_at: datetime | None = None

    @classmethod
    def from_history_record(
        cls,
        record: StructureSchemaHistoryRecord,
    ) -> StructureHistoryRow:
        """Build a history row from a history record."""
        return cls(
            deployment_id=record.deployment_id,
            uid=record.uid,
            namespace=record.namespace,
            object_path=record.object_path,
            structure_name=record.structure_name,
            deployed_at=record.deployed_at,
            structure_schema_snapshot=record.schema_snapshot_json(),
            structure_snapshot=record.structure_snapshot,
            structure_schema_hash=record.structure_schema_hash,
            structure_hash=record.structure_hash,
            diff_summary=record.diff_json(),
            ddl_applied=record.ddl_applied,
            ddl_statements=record.ddl_statements_json(),
            previous_deployment_id=record.previous_deployment_id,
            record_source=record.record_source,
        )
