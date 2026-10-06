from typing import Any, ClassVar

from nld.parameters import ExecutionParameterDefinition
from nld.scheduling.models import EnvironmentScheduling, ScheduleTrigger
from nld.scheduling.services import SchedulingPolicy
from nld.service import EntityTypeNames
from nld.task.base import StandardTask


class SchedulingInfoTask(StandardTask):
    """Display everything declared for one scheduled flow task.

    Covers the scheduled flow, the intended frequency, the effective retry
    budget with where it comes from, the free-form params, and the per
    environment triggers.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        "name",
        ExecutionParameterDefinition(name="namespace", mandatory=False),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        name: str,
        namespace: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.execution_context.load_entities(
            entity_types=[EntityTypeNames.FLOW_TASK],
            namespace=namespace,
        )
        registry = self.execution_context.entity_registry
        self.namespaced_flow_task = registry.get_flow_task(
            entity_key=name,
            namespace=namespace,
        )
        self.task_namespace = str(self.namespaced_flow_task.namespace)
        self.flow_task = self.namespaced_flow_task.model
        self._policy = SchedulingPolicy(
            self.execution_context.project.scheduling_namespace_config,
        )

    def run(self, **kwargs: Any) -> bool:
        """Display the scheduled flow task's declaration."""
        self._display_header()
        self._display_retry_policy()
        self._display_alerting()
        self._display_params()
        self._display_environments()
        return True

    def _display_header(self) -> None:
        """Display the task header and the flow it schedules."""
        title_lines = [f"Scheduled Flow Task: {self.flow_task.name}"]
        title_lines.append(f"Namespace: {self.task_namespace}")
        title_lines.append(f"Flow: {self.flow_task.flow}")
        frequency = self.flow_task.frequency
        title_lines.append(f"Frequency: {frequency if frequency else '(not set)'}")
        self.log_section_header(*title_lines)
        self.log_empty_line()

    def _display_retry_policy(self) -> None:
        """Display the effective retry budget and which declaration set it."""
        resolved = self._policy.resolve_max_attempts(
            flow_task=self.namespaced_flow_task,
        )

        self.log_info("Retry policy:")
        self.log_separator_line()
        self.log_info(f"  Max attempts: {resolved.value}")
        self.log_info(f"  Source: {resolved.origin}")
        self.log_info(
            "  (the count includes the first attempt: 1 means no retry)",
        )
        self.log_separator_line()
        self.log_empty_line()

    def _display_alerting(self) -> None:
        """Display the effective alerting settings and where they come from."""
        resolved = self._policy.resolve_alerting(flow_task=self.namespaced_flow_task)

        self.log_info("Alerting:")
        self.log_separator_line()
        config = resolved.config
        if config is None:
            self.log_info("  (none: this task raises no alert)")
        elif not config.enabled:
            self.log_info("  disabled")
        else:
            self.log_info(f"  transports: {', '.join(config.transports)}")
            self.log_info(f"  alert_on: {', '.join(config.alert_on)}")
            self.log_info(
                "  alert_after_consecutive_failures: "
                f"{config.alert_after_consecutive_failures} "
                "(declared, not applied yet)",
            )
            for name in config.transports:
                for key, value in sorted(config.settings_for(name).items()):
                    self.log_info(f"  {name}.{key}: {value}")
        self.log_info(f"  Source: {resolved.origin}")
        self.log_separator_line()
        self.log_empty_line()

    def _display_params(self) -> None:
        """Display the task's free-form params."""
        params = self.flow_task.params
        self.log_info(f"Params: {len(params)}")
        self.log_separator_line()
        for key in sorted(params):
            self.log_info(f"  - {key}: {params[key]}")
        self.log_separator_line()
        self.log_empty_line()

    def _display_environments(self) -> None:
        """Display the per-environment scheduling declarations."""
        environments = self.flow_task.environments
        self.log_info(f"Environments: {len(environments)}")
        self.log_separator_line()

        for name in sorted(environments):
            env_scheduling = environments[name]
            active = "active" if self.flow_task.is_active_in(name) else "inactive"
            self.log_info(f"  - {name} ({active})")
            self._display_environment_trigger(env_scheduling=env_scheduling)
            frequency = env_scheduling.frequency
            if frequency is not None:
                self.log_info(f"      frequency  : {frequency}")
            if env_scheduling.params:
                self.log_info(f"      params     : {env_scheduling.params}")

        self.log_separator_line()
        self.log_empty_line()

    def _display_environment_trigger(
        self,
        env_scheduling: EnvironmentScheduling,
    ) -> None:
        """Display one environment's trigger, cron or predecessors."""
        trigger = env_scheduling.trigger
        if trigger is None:
            self.log_info("      trigger    : (none)")
            return
        if isinstance(trigger, ScheduleTrigger):
            self.log_info(f"      trigger    : schedule, cron {trigger.cron}")
            return
        predecessors = trigger.get_all_predecessors()
        self.log_info(f"      trigger    : flow, {len(predecessors)} predecessor(s)")
        for predecessor in predecessors:
            scope = "external" if predecessor.external else "local"
            self.log_info(f"        * {predecessor.name} ({scope})")
