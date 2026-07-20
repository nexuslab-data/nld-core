from .deploy_snapshot import DeploySnapshot
from .deploy_target_factory import StructureDeployTargetFactory
from .structure_change import StructureChangeEntry, StructureDeployAction
from .structure_deploy_executor import StructureDeployExecutor
from .structure_deploy_manager import (
    StructureChangeSet,
    StructureDeployManager,
    StructureDeployResult,
)
from .structure_diff import (
    CharacterisationDiff,
    DiffAction,
    FieldDiff,
    StructureDiff,
)
from .structure_diff_computer import StructureDiffComputer
from .structure_diff_ddl_statement_builder import (
    BaseStructureDiffDDLStatementBuilder,
    DDLStatement,
)
from .structure_drift import DeploymentDriftError, DriftReport, classify_drift
from .structure_metadata_backend_manager import StructureMetadataBackendManager
from .structure_metadata_models import StructureHistoryRow, StructureMetadataRow
from .structure_schema_history import (
    StructureSchemaHistoryRecord,
    StructureSchemaSnapshot,
    StructureSchemaSnapshotCharacterisation,
    StructureSchemaSnapshotField,
    build_structure_snapshot_json,
    compute_structure_hash,
    compute_structure_schema_hash,
)

__all__ = [
    "BaseStructureDiffDDLStatementBuilder",
    "DeploySnapshot",
    "CharacterisationDiff",
    "DDLStatement",
    "DeploymentDriftError",
    "DiffAction",
    "DriftReport",
    "FieldDiff",
    "StructureChangeEntry",
    "StructureChangeSet",
    "StructureDeployAction",
    "StructureDeployExecutor",
    "StructureDeployManager",
    "StructureDeployResult",
    "StructureDeployTargetFactory",
    "StructureDiff",
    "StructureDiffComputer",
    "StructureHistoryRow",
    "StructureMetadataBackendManager",
    "StructureMetadataRow",
    "StructureSchemaHistoryRecord",
    "StructureSchemaSnapshot",
    "StructureSchemaSnapshotCharacterisation",
    "StructureSchemaSnapshotField",
    "build_structure_snapshot_json",
    "classify_drift",
    "compute_structure_hash",
    "compute_structure_schema_hash",
]
