from nld.pydantic.base_model import NldBaseModel
from nld.utils import NldStrEnum


class FlowDeployAction(NldStrEnum):
    NEW = "NEW"
    CHANGED = "CHANGED"
    UNCHANGED = "UNCHANGED"
    REMOVED = "REMOVED"


class FlowHashChanges(NldBaseModel):
    """Tracks which individual hash components changed between deployments."""

    python_changed: bool
    sql_changed: bool
    yaml_changed: bool
