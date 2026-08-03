from typing import Any, ClassVar

from nld.parameters import ExecutionParameterDefinition
from nld.scheduling.models import ExecutionFrequency
from nld.scheduling.services import (
    SchedulingFrequencyEntry,
    SchedulingFrequencyReport,
    SchedulingFrequencyReporter,
)
from nld.service import EntityTypeNames
from nld.task.base import StandardTask

UNDECLARED_LABEL = "(undeclared)"


class SchedulingFrequencyTask(StandardTask):
    """Report the intended execution frequency of an environment's assets.

    Lists every flow scheduled in the environment with the frequency it
    declares, the cadence its triggers allow, and whether the two agree. The
    frequency is read from the scheduling declarations only: nothing is
    inferred from a cron, so an asset that declares nothing is reported as
    undeclared instead of being given a made-up cadence.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(
            name="environment",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="frequency",
            mandatory=False,
            allowed_values=sorted(str(value) for value in ExecutionFrequency),
        ),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        environment: str | None = None,
        frequency: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.environment = environment
        self.frequency = ExecutionFrequency(frequency) if frequency else None
        self.execution_context.load_entities(
            entity_types=[
                EntityTypeNames.DATA_FLOW_DEFINITION,
                EntityTypeNames.FLOW_TASK,
            ],
        )

    def run(self, **kwargs: Any) -> bool:
        """Build and render the environment's execution frequency report."""
        environment = self.execution_context.project.environments.resolve_name(
            requested=self.environment,
        )
        report = SchedulingFrequencyReporter(
            environment=environment,
            registry=self.execution_context.entity_registry,
        ).build()

        # The summary is built from the filtered entries so a narrowed report
        # never sums up cadences it did not list.
        report = SchedulingFrequencyReport(
            environment=environment,
            entries=[
                entry
                for entry in report.entries
                if self.frequency is None or entry.frequency == self.frequency
            ],
        )
        entries = report.entries

        self.log_info(f"Execution frequency for environment '{environment}':")
        self.log_separator_line()
        if not entries:
            self.log_info("  No scheduled flow matches")
            self.log_separator_line()
            return True

        self.log_aligned_table(
            headers=[
                "Namespace",
                "Flow",
                "Trigger",
                "Cron",
                "Frequency",
                "Upstream",
                "Status",
            ],
            rows=[self._build_row(entry=entry) for entry in entries],
        )
        self.log_info(f"({len(entries)} scheduled flow(s))")
        self.log_separator_line()
        self._log_summary(report=report)
        return True

    @staticmethod
    def _build_row(entry: SchedulingFrequencyEntry) -> list[str]:
        """Render one report entry as a table row."""
        if entry.is_inconsistent:
            status = "inconsistent"
        elif entry.is_declared:
            status = "ok"
        else:
            status = "undeclared"
        return [
            entry.namespace,
            entry.task_name,
            entry.trigger_kind,
            entry.cron or "",
            str(entry.frequency) if entry.frequency else UNDECLARED_LABEL,
            str(entry.upstream_frequency) if entry.upstream_frequency else "",
            status,
        ]

    def _log_summary(self, report: SchedulingFrequencyReport) -> None:
        """Log the frequency breakdown and the declarations needing attention."""
        counts = report.count_by_frequency()
        if counts:
            self.log_key_value_lines(
                pairs=[(frequency, str(count)) for frequency, count in counts.items()],
            )
        for entry in report.undeclared_entries:
            self.log_warn(
                f"'{entry.node_id}' declares no execution frequency",
            )
        for entry in report.inconsistent_entries:
            self.log_warn(
                f"'{entry.node_id}' declares '{entry.frequency}' but its triggers "
                f"deliver at best '{entry.upstream_frequency}'",
            )
