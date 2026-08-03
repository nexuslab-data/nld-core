from typing import TYPE_CHECKING

from pydantic import Field

from nld.pydantic import NldBaseModel
from nld.scheduling.models import ExecutionFrequency, coarsest_frequency
from nld.scheduling.services.graph import (
    CRON_ATTRIBUTE,
    NAMESPACE_ATTRIBUTE,
    TASK_NAME_ATTRIBUTE,
    TRIGGER_KIND_ATTRIBUTE,
    SchedulingGraph,
)
from nld.scheduling.services.resolver import SchedulingResolver

if TYPE_CHECKING:
    from nld.service import NldEntityRegistry

FLOW_TRIGGER_KIND = "flow"


class SchedulingFrequencyEntry(NldBaseModel):
    """The intended execution frequency of one scheduled asset.

    ``upstream_frequency`` is the coarsest cadence among the assets that
    trigger this one. It is not a fallback for ``frequency`` but the yardstick
    it is checked against: an asset cannot deliver more often than the slowest
    thing it waits for.
    """

    node_id: str
    namespace: str
    task_name: str
    trigger_kind: str
    cron: str | None = None
    frequency: ExecutionFrequency | None = None
    upstream_frequency: ExecutionFrequency | None = None

    @property
    def is_declared(self) -> bool:
        """Whether the asset carries an intended frequency."""
        return self.frequency is not None

    @property
    def is_inconsistent(self) -> bool:
        """Whether the declared cadence outruns what the triggers can deliver."""
        if self.frequency is None or self.upstream_frequency is None:
            return False
        return self.frequency.is_more_frequent_than(self.upstream_frequency)


class SchedulingFrequencyReport(NldBaseModel):
    """Intended execution frequency of every asset scheduled in an environment."""

    environment: str
    entries: list[SchedulingFrequencyEntry] = Field(default_factory=list)

    @property
    def undeclared_entries(self) -> list[SchedulingFrequencyEntry]:
        """Return the scheduled assets with no intended frequency."""
        return [entry for entry in self.entries if not entry.is_declared]

    @property
    def inconsistent_entries(self) -> list[SchedulingFrequencyEntry]:
        """Return the assets whose frequency outruns their triggers."""
        return [entry for entry in self.entries if entry.is_inconsistent]

    def count_by_frequency(self) -> dict[str, int]:
        """Count the declared assets per frequency, most frequent cadence first."""
        counts: dict[str, int] = {}
        for frequency in ExecutionFrequency:
            matching = [entry for entry in self.entries if entry.frequency == frequency]
            if matching:
                counts[str(frequency)] = len(matching)
        return counts


class SchedulingFrequencyReporter:
    """Builds the frequency report of a single environment.

    Frequencies are read from the scheduling declarations, never inferred from
    a cron: the report is exactly what the project claims about its assets, so
    a missing declaration shows up as missing instead of being invented.
    """

    def __init__(self, environment: str, registry: "NldEntityRegistry") -> None:
        self._environment = environment
        self._registry = registry

    def build(self) -> SchedulingFrequencyReport:
        """Resolve the environment's graph and report each asset's frequency."""
        graph = SchedulingResolver(
            environment=self._environment,
            registry=self._registry,
        ).resolve()

        entries = [
            self._build_entry(graph=graph, node_id=node_id)
            for node_id in graph.local_node_ids()
        ]
        return SchedulingFrequencyReport(
            environment=self._environment,
            entries=entries,
        )

    def _build_entry(
        self,
        graph: SchedulingGraph,
        node_id: str,
    ) -> SchedulingFrequencyEntry:
        """Build the report entry of a single scheduling node."""
        attributes = graph.get_node_attributes(node_id=node_id)
        return SchedulingFrequencyEntry(
            node_id=node_id,
            namespace=attributes[NAMESPACE_ATTRIBUTE],
            task_name=attributes[TASK_NAME_ATTRIBUTE],
            trigger_kind=attributes[TRIGGER_KIND_ATTRIBUTE],
            cron=attributes[CRON_ATTRIBUTE],
            frequency=graph.get_frequency(node_id=node_id),
            upstream_frequency=self._resolve_upstream_frequency(
                graph=graph,
                node_id=node_id,
            ),
        )

    def _resolve_upstream_frequency(
        self,
        graph: SchedulingGraph,
        node_id: str,
    ) -> ExecutionFrequency | None:
        """Return the coarsest cadence among the assets triggering a node."""
        return self._collect_upstream_frequency(
            graph=graph,
            node_id=node_id,
            visited={node_id},
        )

    def _collect_upstream_frequency(
        self,
        graph: SchedulingGraph,
        node_id: str,
        visited: set[str],
    ) -> ExecutionFrequency | None:
        """Return the coarsest cadence of the direct triggers of a node."""
        frequencies: list[ExecutionFrequency] = []
        for upstream_id in graph.upstream_node_ids(node_id=node_id):
            if upstream_id in visited:
                continue
            upstream_frequency = self._resolve_effective_frequency(
                graph=graph,
                node_id=upstream_id,
                visited=visited | {upstream_id},
            )
            if upstream_frequency is not None:
                frequencies.append(upstream_frequency)
        return coarsest_frequency(frequencies=frequencies)

    def _resolve_effective_frequency(
        self,
        graph: SchedulingGraph,
        node_id: str,
        visited: set[str],
    ) -> ExecutionFrequency | None:
        """Return a node's cadence, walking up flow triggers when undeclared.

        An undeclared flow-triggered asset still has a cadence: the one its own
        triggers impose. Walking up recovers it so the check stays useful in a
        chain where only the schedule roots carry a declaration. ``visited``
        keeps the walk finite even on a graph that was never validated.
        """
        declared = graph.get_frequency(node_id=node_id)
        if declared is not None:
            return declared

        attributes = graph.get_node_attributes(node_id=node_id)
        if attributes[TRIGGER_KIND_ATTRIBUTE] != FLOW_TRIGGER_KIND:
            return None

        return self._collect_upstream_frequency(
            graph=graph,
            node_id=node_id,
            visited=visited,
        )
