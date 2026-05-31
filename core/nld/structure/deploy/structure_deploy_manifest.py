from __future__ import annotations

import datetime

from nld.pydantic.base_model import NldBaseModel
from nld.structure.deploy.structure_diff import CharacterisationDiff, FieldDiff
from nld.utils import NldStrEnum


class StructureDeployAction(NldStrEnum):
    ALTER = "ALTER"
    CREATE = "CREATE"
    NONE = "NONE"


class StructureDeployManifestEntry(NldBaseModel):
    """A single structure entry in the deployment manifest."""

    action: StructureDeployAction
    characterisation_diffs: list[CharacterisationDiff] = []
    field_diffs: list[FieldDiff] = []
    namespace: str
    structure_name: str


class StructureDeployScope(NldBaseModel):
    """Describes the scope used to generate the manifest."""

    name: str | None = None
    namespace: str | None = None


class StructureDeployManifest(NldBaseModel):
    """Deployment manifest containing structure change entries."""

    created_at: datetime.datetime
    entries: list[StructureDeployManifestEntry]
    manifest_id: str
    scope: StructureDeployScope
    version: str = "1.0"
