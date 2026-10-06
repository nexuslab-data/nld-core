from pydantic import Field

from nld.pydantic import NldBaseModel
from nld.utils import NldStrEnum


class FlowAlertLevel(NldStrEnum):
    """How serious the alerted outcome is.

    The values are the execution states a project lists in
    ``alerting.alert_on``, so one declaration filters both the alerts nld
    raises itself and the ones its scheduler raises for it.
    """

    WARNING = "WARNING"
    FAILED = "FAILED"


class FlowAlertItem(NldBaseModel):
    """One line of detail in an alert: a violated check, an error."""

    detail: str
    label: str


class FlowAlert(NldBaseModel):
    """What nld reports about one flow execution."""

    environment: str | None = None
    execution_reference: str | None = None
    execution_url: str | None = None
    execution_status: str
    flow_name: str
    flow_namespace: str
    flow_uid: str
    items: list[FlowAlertItem] = Field(default_factory=list)
    level: FlowAlertLevel
    project_name: str | None = None
    summary: str

    @property
    def flow_path(self) -> str:
        """The flow's dotted identity, as a reader knows it."""
        return f"{self.flow_namespace}.{self.flow_name}"


class FlowExecutionOutcome(NldBaseModel):
    """What a scheduler needs to know once the execution is over.

    ``alerted`` is the fact a scheduler keys its own alerting on: when nld
    already raised the alert, the scheduler stays quiet and only reacts to
    failures nld could not report (a pod that never started, an out-of-memory
    kill, a crash before the flow ran).
    """

    alert_level: FlowAlertLevel | None = None
    alerted: bool = False
    execution_status: str
