from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from nld.connector.base.deploy_capabilities import (
    ConnectorDeployCapabilities,
    normalize_comparable_data_type,
)
from nld.pydantic.base_model import NldBaseModel
from nld.structure.deploy.structure_diff import StructureDiff
from nld.structure.field.field import Field
from nld.structure.structure.structure import Structure
from nld.structure.structure.structure_characterisation import (
    StructureCharacterisation,
)


class StructureSchemaSnapshotField(NldBaseModel):
    """Serializable representation of a single field in a schema snapshot."""

    name: str
    data_type: str
    length: int = 0
    precision: int = 0
    nullable: bool = True
    default_value: str | int | None = None

    @classmethod
    def from_field(
        cls,
        field: Field,
        in_primary_key: bool = False,
        capabilities: ConnectorDeployCapabilities | None = None,
    ) -> StructureSchemaSnapshotField:
        """Build a snapshot field from a Structure Field.

        Primary-key members are never nullable in the database, so
        the snapshot records them as non-nullable even when the
        definition does not carry an explicit mandatory
        characterisation — keeping definition-derived and
        introspection-derived snapshots comparable.

        The data type is stored in its canonical comparable form for
        the same reason: engines spell semantically-equal types
        differently on read-back (Snowflake reports a declared
        ``NUMERIC`` as ``NUMBER``), and a raw-spelling snapshot would
        hash a schema as changed when nothing physical changed.
        """
        return cls(
            name=field.name,
            data_type=normalize_comparable_data_type(
                data_type=field.data_type,
                capabilities=capabilities,
            ),
            length=field.length,
            precision=field.precision,
            nullable=not (field.is_mandatory() or in_primary_key),
            default_value=field.default_value,
        )


class StructureSchemaSnapshotCharacterisation(NldBaseModel):
    """Serializable representation of a structure-level characterisation."""

    name: str
    characterisation_type: str
    linked_fields: list[str] = []

    @classmethod
    def from_characterisation(
        cls,
        characterisation: StructureCharacterisation,
    ) -> StructureSchemaSnapshotCharacterisation:
        """Build a snapshot characterisation from a StructureCharacterisation.

        The name is lowercased because case-folding engines report
        constraint names uppercase on read-back (Snowflake), and the
        snapshot must hash equal across the definition-derived and
        introspection-derived sides.
        """
        return cls(
            name=characterisation.name.lower(),
            characterisation_type=characterisation.characterisation,
            linked_fields=characterisation.linked_fields or [],
        )


class StructureSchemaSnapshot(NldBaseModel):
    """Fully expanded schema snapshot of a structure at a point in time.

    Captures all physical attributes relevant to the database schema,
    including fields inherited from templates. Excludes non-physical
    metadata like descriptions, tags, and properties.
    """

    structure_name: str
    structure_type: str
    namespace: str
    fields: list[StructureSchemaSnapshotField] = []
    characterisations: list[StructureSchemaSnapshotCharacterisation] = []
    snapshot_timestamp: datetime

    @classmethod
    def from_structure(
        cls,
        structure: Structure,
        namespace: str,
        capabilities: ConnectorDeployCapabilities | None = None,
    ) -> StructureSchemaSnapshot:
        """Build a snapshot from a Structure with templates expanded.

        Uses get_all_fields() to include template-inherited fields
        in their correct order. ``capabilities`` carries the engine's
        comparable data type aliases so the snapshot hashes equal
        across declared and read-back spellings.
        """
        all_fields = structure.get_all_fields()
        primary_key_field_names = {
            field.name for field in structure.get_primary_key_fields()
        }
        snapshot_fields = [
            StructureSchemaSnapshotField.from_field(
                field=field,
                in_primary_key=field.name in primary_key_field_names,
                capabilities=capabilities,
            )
            for field in all_fields
        ]
        snapshot_characterisations = [
            StructureSchemaSnapshotCharacterisation.from_characterisation(
                characterisation=char,
            )
            for char in structure.get_deployable_characterisations()
        ]
        return cls(
            structure_name=structure.name,
            structure_type=structure.structure_type,
            namespace=namespace,
            fields=snapshot_fields,
            characterisations=snapshot_characterisations,
            snapshot_timestamp=datetime.now(tz=UTC),
        )

    def to_json(self) -> str:
        """Serialize the snapshot to a JSON string."""
        return json.dumps(
            self.model_dump(mode="json"),
            default=str,
        )

    def to_hashable_json(self) -> str:
        """Serialize the snapshot to a deterministic JSON string for hashing.

        Excludes snapshot_timestamp since it changes on every call
        and would prevent deterministic hash comparison.
        """
        data = self.model_dump(mode="json")
        data.pop("snapshot_timestamp", None)
        return json.dumps(
            data,
            sort_keys=True,
            default=str,
        )


def compute_structure_schema_hash(schema_snapshot: StructureSchemaSnapshot) -> str:
    """Compute a SHA256 hash of the schema snapshot (physical attributes only)."""
    content = schema_snapshot.to_hashable_json()
    return hashlib.sha256(content.encode("utf-8")).hexdigest().upper()


def compute_structure_hash(structure: Structure) -> str:
    """Compute a SHA256 hash of the full structure definition."""
    content = build_structure_snapshot_json(structure=structure)
    return hashlib.sha256(content.encode("utf-8")).hexdigest().upper()


def build_structure_snapshot_json(structure: Structure) -> str:
    """Serialize a structure definition to JSON for storage.

    Uses structure.to_dict() to capture the complete definition
    including all metadata, templates, properties, and tags.
    """
    return json.dumps(
        structure.to_dict(),
        default=str,
    )


class StructureSchemaHistoryRecord(NldBaseModel):
    """A single deployment event in the schema history log.

    Records the schema snapshot, the structure definition snapshot,
    the diff that triggered the deployment, and whether DDL was
    actually applied.
    """

    deployment_id: str
    uid: str
    namespace: str
    object_path: str
    structure_name: str
    deployed_at: datetime
    structure_schema_snapshot: StructureSchemaSnapshot
    structure_snapshot: str
    structure_schema_hash: str
    structure_hash: str
    diff_summary: StructureDiff | None = None
    ddl_applied: bool = False
    ddl_statements: list[str] = []
    previous_deployment_id: str | None = None
    record_source: str = "deployment"

    @classmethod
    def build(
        cls,
        namespace: str,
        object_path: str,
        structure_name: str,
        structure_schema_snapshot: StructureSchemaSnapshot,
        structure_snapshot: str,
        structure_schema_hash: str,
        structure_hash: str,
        diff: StructureDiff | None = None,
        ddl_applied: bool = False,
        ddl_statements: list[str] | None = None,
        previous_deployment_id: str | None = None,
        record_source: str = "deployment",
        uid: str | None = None,
    ) -> StructureSchemaHistoryRecord:
        """Create a new history record with auto-generated ID and timestamp.

        The ``uid`` is the stable backend asset identity: minted on
        the first record of an asset and carried through every later
        record, including across declared renames.
        """
        return cls(
            deployment_id=str(uuid.uuid4()),
            uid=uid if uid is not None else str(uuid.uuid4()),
            namespace=namespace,
            object_path=object_path,
            structure_name=structure_name,
            deployed_at=datetime.now(tz=UTC),
            structure_schema_snapshot=structure_schema_snapshot,
            structure_snapshot=structure_snapshot,
            structure_schema_hash=structure_schema_hash,
            structure_hash=structure_hash,
            diff_summary=diff,
            ddl_applied=ddl_applied,
            ddl_statements=ddl_statements or [],
            previous_deployment_id=previous_deployment_id,
            record_source=record_source,
        )

    def schema_snapshot_json(self) -> str:
        """Serialize the schema snapshot to JSON."""
        return self.structure_schema_snapshot.to_json()

    def diff_json(self) -> str:
        """Serialize the diff summary to JSON."""
        if self.diff_summary is None:
            return "{}"
        return json.dumps(
            self.diff_summary.model_dump(mode="json"),
            default=str,
        )

    def ddl_statements_json(self) -> str:
        """Serialize DDL statements list to JSON."""
        return json.dumps(self.ddl_statements)
