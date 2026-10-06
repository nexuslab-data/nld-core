from collections.abc import Sequence
from string import Template
from typing import TYPE_CHECKING

from nld.flow.alerting.models import (
    FlowAlert,
    FlowAlertingRuntimeSettings,
    FlowAlertItem,
    FlowAlertLevel,
    FlowExecutionOutcome,
)
from nld.flow.alerting.transports.base import FlowAlertTransport
from nld.flow.utils import FlowExecStatus
from nld.utils.mixin import NldMixIn

# nld.flow.alerting sits below nld.flow.config in the import order (the flow
# config declares the transport manifests), so the execution and quality
# models can only be referenced for typing here.
if TYPE_CHECKING:
    from nld.flow.execution import FlowExecutionInfo
    from nld.flow.quality.models import DataQualityCheckResult
    from nld.scheduling.config import AlertingConfig

MAX_ERROR_SUMMARY_LENGTH = 1000


class FlowAlertingService(NldMixIn):
    """Decides whether one flow execution's outcome is alerted, and does it.

    nld is the component that knows *why* an execution ended the way it did
    — a violated data quality check, the exception a flow raised — so nld
    raises the alert for those. The scheduler running it only has the exit
    code; it alerts on what nld could not report (a pod that never started,
    an out-of-memory kill) and keeps quiet whenever the outcome line says
    nld already did.

    The levels map on the three data quality severities: a ``warning``
    violation raises a WARNING alert; an ``error`` violation raises a FAILED
    alert but the execution still completes, so the pipeline goes on; a
    ``blocking`` violation, like any flow exception, raises a FAILED alert
    and fails the execution.

    ``config`` is the ``scheduling.alerting`` declaration in force for the
    flow's namespace (None when the project declares none), ``settings``
    the transport-neutral runtime side handed over by the scheduler,
    ``transports`` the technologies actually configured in this
    environment — the declared ones whose secrets were handed over. With
    none, nothing is ever posted. Built per flow by the execution context's
    ``FlowAlertingProvider``; it never looks anything up itself.
    """

    def __init__(
        self,
        config: "AlertingConfig | None",
        settings: FlowAlertingRuntimeSettings | None = None,
        transports: Sequence[FlowAlertTransport] = (),
        project_name: str | None = None,
        environment: str | None = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._environment = environment
        self._project_name = project_name
        self._settings = (
            settings if settings is not None else FlowAlertingRuntimeSettings()
        )
        self._transports = tuple(transports)

    @property
    def settings(self) -> FlowAlertingRuntimeSettings:
        """The runtime side handed over by the scheduler."""
        return self._settings

    @property
    def transports(self) -> tuple[FlowAlertTransport, ...]:
        """The technologies configured in this environment."""
        return self._transports

    @property
    def transport_names(self) -> list[str]:
        """The technologies this service alerts through, by name."""
        return [transport.name for transport in self._transports]

    @property
    def is_enabled(self) -> bool:
        """Whether this service can raise alerts at all."""
        return (
            self._config is not None
            and self._config.enabled
            and len(self._transports) > 0
        )

    @staticmethod
    def resolve_level(
        execution_status: str | None,
        quality_results: "Sequence[DataQualityCheckResult]" = (),
        error: BaseException | None = None,
    ) -> FlowAlertLevel | None:
        """Map an execution outcome onto an alert level, None when clean.

        A failed execution is FAILED. A completed-with-warning execution is
        FAILED when a check declared with the error severity was violated
        (the step failed, the execution went on) and WARNING otherwise.
        """
        if error is not None or execution_status == FlowExecStatus.FAILED:
            return FlowAlertLevel.FAILED
        if execution_status == FlowExecStatus.SUCCEEDED_WITH_WARNING:
            if any(result.is_step_failure for result in quality_results):
                return FlowAlertLevel.FAILED
            return FlowAlertLevel.WARNING
        return None

    def should_alert(self, level: FlowAlertLevel) -> bool:
        """Whether an outcome at this level is alerted by nld itself.

        A failure on a non-final attempt is not: the scheduler retries it,
        and only the last attempt's failure is worth a message. The level
        values are execution states, the vocabulary of ``alert_on``.
        """
        if not self.is_enabled or self._config is None:
            return False
        if level.value not in self._config.alert_on:
            return False
        if level == FlowAlertLevel.FAILED and not self._settings.is_final_attempt:
            return False
        return True

    def build_alert(
        self,
        level: FlowAlertLevel,
        execution_status: str,
        flow_execution_info: "FlowExecutionInfo",
        quality_results: "Sequence[DataQualityCheckResult]" = (),
        error: BaseException | None = None,
    ) -> FlowAlert:
        """Assemble the message for an outcome."""
        violated = [result for result in quality_results if not result.is_valid]
        items = [self._quality_item(result=result) for result in violated]
        if error is not None:
            summary = str(error) or error.__class__.__name__
        elif violated:
            summary = f"{len(violated)} data quality check(s) violated"
        else:
            summary = f"Execution finished in state {execution_status}"
        return FlowAlert(
            environment=self._environment,
            execution_reference=self._settings.execution_reference,
            execution_url=self._settings.execution_url,
            execution_status=execution_status,
            flow_name=flow_execution_info.flow_name,
            flow_namespace=flow_execution_info.flow_namespace,
            flow_uid=flow_execution_info.flow_uid,
            items=items,
            level=level,
            project_name=self._project_name,
            summary=summary[:MAX_ERROR_SUMMARY_LENGTH],
        )

    @staticmethod
    def _quality_item(result: "DataQualityCheckResult") -> FlowAlertItem:
        label = (
            result.rule if result.column is None else f"{result.rule} ({result.column})"
        )
        detail = f"{result.status}/{result.severity}"
        if result.message:
            detail += f": {result.message}"
        measures = [
            f"{name}={value}"
            for name, value in (
                ("observed", result.observed),
                ("expected", result.expected),
                ("violations", result.violation_count),
            )
            if value is not None
        ]
        if measures:
            detail += f" ({', '.join(measures)})"
        return FlowAlertItem(
            detail=detail,
            label=label,
        )

    def notify(self, alert: FlowAlert) -> bool:
        """Send the alert through every transport; True when at least one delivered.

        A transport that fails is logged and skipped: losing an alert must
        never fail the run, and the outcome line still tells the scheduler
        whether anyone was told.
        """
        delivered: list[str] = []
        for transport in self._transports:
            try:
                transport.send(alert=alert)
            except Exception as ex:
                self.log_warn(
                    f"Alert could not be delivered through '{transport.name}' "
                    f"({alert.level.value}): {ex}"
                )
                continue
            delivered.append(transport.name)
        if delivered:
            self.log_info(
                f"Alert delivered ({alert.level.value}) through "
                f"{', '.join(delivered)}: {alert.summary}"
            )
        return bool(delivered)

    def build_outcome_line(self, outcome: FlowExecutionOutcome) -> str | None:
        """Render the outcome line the scheduler reads back, if one is asked."""
        template = self._settings.outcome_line_template
        if template is None:
            return None
        return Template(template).safe_substitute(
            status=outcome.execution_status,
            alerted="true" if outcome.alerted else "false",
            level=outcome.alert_level.value if outcome.alert_level else "",
        )
