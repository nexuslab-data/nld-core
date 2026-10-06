from typing import Any, ClassVar

from nld.parameters import ExecutionParameterDefinition
from nld.scheduling.models import FlowTask, NamespacedFlowTaskModel, ScheduleTrigger
from nld.scheduling.services import SchedulingPolicy
from nld.service import EntityTypeNames
from nld.task.base import StandardTask


class SchedulingListTask(StandardTask):
    """List the project's scheduled flow tasks.

    ``--namespace`` scopes the listing. ``--env`` restricts it to the tasks
    actually scheduled in that environment, which is what you want when
    answering "what runs in prd?" rather than "what is declared?".
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(name="namespace", mandatory=False),
        ExecutionParameterDefinition(name="environment", mandatory=False),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        namespace: str | None = None,
        environment: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.namespace = namespace
        self.environment = environment
        self.execution_context.load_entities(
            entity_types=[EntityTypeNames.FLOW_TASK],
            namespace=self.namespace,
        )
        self._policy = SchedulingPolicy(
            self.execution_context.project.scheduling_namespace_config,
        )

    def run(self, **kwargs: Any) -> bool:
        """Display the matching scheduled flow tasks as a table."""
        registry = self.execution_context.entity_registry
        flow_tasks = registry.get_flow_task_dict(namespace=self.namespace)

        self.log_info("Scheduled Flow Tasks:")
        if self.environment:
            self.log_info(f"Environment: {self.environment}")
        self.log_separator_line()

        headers = [
            "Name",
            "Namespace",
            "Flow",
            "Frequency",
            "Max attempts",
            "Environments",
        ]
        rows: list[list[str]] = []
        for key in sorted(flow_tasks):
            namespaced = flow_tasks[key]
            flow_task = namespaced.model
            if self.environment and not flow_task.is_active_in(self.environment):
                continue
            rows.append(
                [
                    key,
                    str(namespaced.namespace),
                    str(flow_task.flow),
                    self._frequency(flow_task=flow_task),
                    str(self._max_attempts(namespaced=namespaced)),
                    ", ".join(self._environments(flow_task=flow_task)) or "(none)",
                ]
            )

        if not rows:
            self.log_info("  No scheduled flow tasks match")
            self.log_separator_line()
            return True

        self.log_aligned_table(
            headers=headers,
            rows=rows,
        )
        self.log_info(f"({len(rows)} scheduled flow task(s))")
        self.log_separator_line()
        return True

    def _max_attempts(self, namespaced: NamespacedFlowTaskModel) -> int:
        """Return the task's effective retry budget."""
        return self._policy.max_attempts(flow_task=namespaced)

    def _frequency(self, flow_task: FlowTask) -> str:
        """Return the declared frequency, environment override included."""
        frequency = (
            flow_task.resolved_frequency(self.environment)
            if self.environment
            else flow_task.frequency
        )
        return str(frequency) if frequency else ""

    @staticmethod
    def _environments(flow_task: FlowTask) -> list[str]:
        """Return each environment with its trigger kind, disabled ones flagged."""
        entries: list[str] = []
        for name in sorted(flow_task.environments):
            env_scheduling = flow_task.environments[name]
            if not env_scheduling.enabled:
                entries.append(f"{name}(disabled)")
                continue
            trigger = env_scheduling.trigger
            if trigger is None:
                entries.append(f"{name}(no trigger)")
                continue
            kind = "schedule" if isinstance(trigger, ScheduleTrigger) else "flow"
            entries.append(f"{name}({kind})")
        return entries
