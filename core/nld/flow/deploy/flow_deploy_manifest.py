import datetime

from nld.flow.deploy.flow_deploy_diff import FlowDeployAction, FlowHashChanges
from nld.pydantic.base_model import NldBaseModel
from nld.structure.deploy.structure_deploy_manifest import StructureDeployManifestEntry
from nld.utils import NldStrEnum


class BackfillStrategy(NldStrEnum):
    COLUMN = "COLUMN"
    FULL = "FULL"
    NONE = "NONE"


class DeployLink(NldBaseModel):
    """A directed dependency edge in the deployment graph."""

    source_id: str
    source_type: str
    target_id: str
    target_type: str


class StructureDeployEntry(StructureDeployManifestEntry):
    """Structure entry in a flow deployment manifest.

    Extends the base structure deploy entry with flow-specific
    field rename mapping.
    """

    field_naming_change_mapping: dict[str, str] = {}


class FlowDeployEntry(NldBaseModel):
    """A single flow entry in the deploy manifest."""

    namespace: str
    flow_name: str
    action: FlowDeployAction
    backfill_columns: list[str] = []
    backfill_strategy: BackfillStrategy = BackfillStrategy.NONE
    hash_changes: FlowHashChanges | None = None


class DeployScope(NldBaseModel):
    """Describes the scope of a deployment manifest."""

    downstream: bool = False
    flow_name: str | None = None
    namespace: str | None = None
    upstream: bool = False


class DeployManifest(NldBaseModel):
    """Top-level deployment manifest written by the planner.

    Serialized to YAML at
    ``<entities_root>/.deployments/flows/<timestamp>_<scope>.yaml``.
    """

    manifest_id: str
    version: str = "1.0"
    created_at: datetime.datetime
    scope: DeployScope
    flows: list[FlowDeployEntry]
    structures: list[StructureDeployEntry] = []
    links: list[DeployLink] = []
