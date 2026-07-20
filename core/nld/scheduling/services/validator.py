from typing import TYPE_CHECKING

from nld.scheduling.scheduling_exceptions import NldSchedulingCycleError
from nld.scheduling.services.graph import SchedulingGraph
from nld.scheduling.services.resolver import SchedulingResolver

if TYPE_CHECKING:
    from nld.service import NldEntityRegistry


class SchedulingValidator:
    """Validates the scheduling graph of a single environment.

    Validation resolves every flow reference (a dangling reference raises) and
    asserts the environment's trigger graph is acyclic. It is environment
    scoped on purpose: a cycle can exist in one environment's derived graph
    while another stays acyclic because a flow is disabled there.
    """

    def __init__(self, environment: str, registry: "NldEntityRegistry") -> None:
        self._environment = environment
        self._registry = registry

    def validate(self) -> SchedulingGraph:
        """Resolve and validate the graph, raising on cycles."""
        graph = SchedulingResolver(
            environment=self._environment,
            registry=self._registry,
        ).resolve()
        cycle = graph.find_cycle()
        if cycle is not None:
            raise NldSchedulingCycleError(cycle=cycle)
        return graph
