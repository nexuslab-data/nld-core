from __future__ import annotations

from nld.pydantic.base_model import NldBaseModel
from nld.structure.deploy.structure_diff import CharacterisationDiff, FieldDiff
from nld.utils import NldStrEnum


class StructureDeployAction(NldStrEnum):
    ALTER = "ALTER"
    CREATE = "CREATE"
    FAILED = "FAILED"
    NONE = "NONE"
    REBUILD = "REBUILD"


class StructureChangeEntry(NldBaseModel):
    """A single structure entry in an in-memory change set.

    Computed at deploy time against the live target and never
    persisted — the preview prints it, the apply recomputes the
    actual DDL against the target before executing.

    A ``FAILED`` entry records a structure whose planning raised
    (target resolution, connector opening or change-set computation):
    it carries the error in ``planning_error``, is shown in preview,
    and fails at apply time instead of silently vanishing from the
    run.
    """

    action: StructureDeployAction
    characterisation_diffs: list[CharacterisationDiff] = []
    ddl_statements: list[str] = []
    dependent_views: list[str] = []
    field_diffs: list[FieldDiff] = []
    namespace: str
    planning_error: str | None = None
    structure_name: str
    view_flows_to_execute: list[str] = []
