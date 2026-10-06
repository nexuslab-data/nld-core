from nld.pydantic import NldBaseModel
from nld.scheduling.config import (
    DEFAULT_MAX_ATTEMPTS,
    AlertingConfig,
    SchedulingNamespaceConfig,
)
from nld.scheduling.models import NamespacedFlowTaskModel

MAX_ATTEMPTS_TASK_ORIGIN = "task override (max_attempts)"
NO_ALERTING_ORIGIN = "no alerting declared"


class ResolvedMaxAttempts(NldBaseModel):
    """A task's retry budget together with the declaration that set it.

    ``origin`` is meant to be shown to a reader — `nld scheduling info` prints
    it — so a surprising budget can be traced to the line that caused it
    instead of leaving the reader to guess which level won.
    """

    value: int
    origin: str


class ResolvedAlerting(NldBaseModel):
    """A task's alerting declaration together with where it comes from.

    ``config`` is None when no level declares alerting, which reads as "this
    task is not alerted on" rather than as an error: alerting is opt-in per
    namespace. A declaration that switches alerting off is kept, so
    ``origin`` can still point a reader at the line that did it.
    """

    config: AlertingConfig | None = None
    origin: str

    @property
    def enabled(self) -> bool:
        """Whether the task raises alerts at all."""
        return self.config is not None and self.config.enabled


class SchedulingPolicy:
    """Resolves one project's namespace-scoped scheduling settings.

    Bound to a single project's ``scheduling_namespace_config``: a process may
    hold several projects at once (the scheduling generator loads a whole
    catalog before rendering it), so the policy is constructed per project
    rather than read from an ambient context.

    Example:
        >>> policy = SchedulingPolicy(project.scheduling_namespace_config)
        >>> policy.max_attempts(flow_task=namespaced_task)
        2
    """

    def __init__(
        self,
        scheduling_namespace_config: SchedulingNamespaceConfig,
    ) -> None:
        self._scheduling_namespace_config = scheduling_namespace_config

    def max_attempts(self, flow_task: NamespacedFlowTaskModel) -> int:
        """Return how many times a scheduled task may run before it is failed.

        The count includes the first attempt: 1 means no retry, 2 means one
        retry.
        """
        return self.resolve_max_attempts(flow_task=flow_task).value

    def resolve_max_attempts(
        self,
        flow_task: NamespacedFlowTaskModel,
    ) -> ResolvedMaxAttempts:
        """Return the task's retry budget and the declaration behind it.

        The task's own ``max_attempts`` wins when set; otherwise the nearest
        namespace mapping applies, falling back to the built-in default.
        Renderers should go through this rather than reading either level
        directly, so the precedence stays in one place.
        """
        if flow_task.model.max_attempts is not None:
            return ResolvedMaxAttempts(
                value=flow_task.model.max_attempts,
                origin=MAX_ATTEMPTS_TASK_ORIGIN,
            )

        namespace = str(flow_task.namespace)
        matching_key = self._scheduling_namespace_config.find_matching_key(
            namespace=namespace,
        )
        if matching_key is None:
            return ResolvedMaxAttempts(
                value=DEFAULT_MAX_ATTEMPTS,
                origin=f"built-in default ({DEFAULT_MAX_ATTEMPTS})",
            )
        return ResolvedMaxAttempts(
            value=self._scheduling_namespace_config.get_max_attempts(
                namespace=namespace,
            ),
            origin=f"namespaces['{matching_key}'].scheduling",
        )

    def alerting(self, flow_task: NamespacedFlowTaskModel) -> AlertingConfig | None:
        """Return the alerting in force for a task, None when it raises none.

        None covers both "nothing declared" and "declared, then switched off";
        renderers only need to know whether to alert and on what. See
        ``resolve_alerting`` for the distinction.
        """
        return self.alerting_for_namespace(namespace=str(flow_task.namespace))

    def resolve_alerting(
        self,
        flow_task: NamespacedFlowTaskModel,
    ) -> ResolvedAlerting:
        """Return the task's alerting declaration and where it comes from."""
        return self.resolve_alerting_for_namespace(
            namespace=str(flow_task.namespace),
        )

    def alerting_for_namespace(self, namespace: str) -> AlertingConfig | None:
        """The alerting in force for a namespace, None when it raises none.

        The same answer a scheduled task gets, keyed on the namespace alone
        so a running flow — which has its namespace but no task — resolves
        its alerting through the same rules.
        """
        resolved = self.resolve_alerting_for_namespace(namespace=namespace)
        return resolved.config if resolved.enabled else None

    def resolve_alerting_for_namespace(self, namespace: str) -> ResolvedAlerting:
        """Return a namespace's alerting declaration and where it comes from.

        Resolution walks past namespaces declaring no alerting rather than
        stopping at the nearest mapping, so a layer raising only its retry
        budget does not switch alerting off for itself. See
        ``SchedulingNamespaceConfig.find_alerting_key``.
        """
        alerting_key = self._scheduling_namespace_config.find_alerting_key(
            namespace=namespace,
        )
        if alerting_key is None:
            return ResolvedAlerting(origin=NO_ALERTING_ORIGIN)
        return ResolvedAlerting(
            config=self._scheduling_namespace_config.get_alerting(
                namespace=namespace,
            ),
            origin=f"namespaces['{alerting_key}'].scheduling.alerting",
        )
