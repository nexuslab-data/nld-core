import datetime

from nld.deploy.change_file_models import PendingChangeFile
from nld.flow.deploy.flow_deploy_diff import FlowDeployAction, FlowHashChanges
from nld.pydantic.base_model import NldBaseModel
from nld.structure.deploy.structure_change import StructureChangeEntry


class DeployLink(NldBaseModel):
    """A directed dependency edge in the deployment graph."""

    source_id: str
    source_type: str
    target_id: str
    target_type: str


class FlowChangeEntry(NldBaseModel):
    """A single flow entry in the in-memory change set."""

    namespace: str
    flow_name: str
    action: FlowDeployAction
    hash_changes: FlowHashChanges | None = None


class DeployScope(NldBaseModel):
    """Describes the scope of a change set."""

    downstream: bool = False
    flow_name: str | None = None
    namespace: str | None = None
    upstream: bool = False


class FlowChangeSet(NldBaseModel):
    """In-memory change set computed against the live target at deploy time.

    Never persisted: the preview prints it and the executor applies
    it immediately. The DDL is always recomputed against the actual
    target when applying.
    """

    changeset_id: str
    created_at: datetime.datetime
    scope: DeployScope
    flows: list[FlowChangeEntry]
    structures: list[StructureChangeEntry] = []
    links: list[DeployLink] = []
    pending_change_files: list[PendingChangeFile] = []

    def is_empty(self) -> bool:
        """Return True when the change set carries no change at all."""
        return not self.flows and not self.structures and not self.pending_change_files
