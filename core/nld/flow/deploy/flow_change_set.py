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
    """Describes the scope of a change set.

    ``namespaces`` holds the roots of the deployment units a namespace
    deploy resolved to, ``groups`` the deploy groups that widened it, and
    ``lock_keys`` the deploy targets the change set may change, which
    the executor locks while applying it.
    """

    downstream: bool = False
    flow_name: str | None = None
    namespace: str | None = None
    upstream: bool = False
    groups: list[str] = []
    lock_keys: list[str] = []
    namespaces: list[str] = []

    def describe(self) -> str:
        """Describe the scope for lock holders and logs.

        Example: ``namespace 'crm' (deploy group customer: crm, support)``.
        """
        if self.namespace is None:
            description = "the whole project"
        else:
            description = f"namespace '{self.namespace}'"
        if self.groups:
            description += (
                f" (deploy group {', '.join(self.groups)}: "
                f"{', '.join(self.namespaces)})"
            )
        if self.flow_name is not None:
            description += f", flow '{self.flow_name}'"
        return description


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
