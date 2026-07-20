from typing import Any

from pydantic import Field

from nld.flow.definition import DataFlowDefinition
from nld.pydantic import (
    NldBaseModel,
    NldEntityReference,
    NldNamedBaseModel,
    NldNamespacedBaseModelWrapper,
)
from nld.scheduling.models.trigger import FlowPrecondition, FlowTrigger, Trigger


class EnvironmentScheduling(NldBaseModel):
    """How a flow is scheduled in one environment.

    A flow is scheduled in an environment only when it is present, ``enabled``
    and carries a ``trigger``. ``params`` provides env-level overrides of the
    flow-level ``params``.
    """

    enabled: bool = True
    trigger: Trigger | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class FlowScheduling(NldNamedBaseModel):
    """Scheduling for a single flow, keyed by environment.

    ``flow`` is an entity reference to the scheduled DataFlowDefinition, so the
    link is registry-resolved and validated. Everything platform-specific
    (data_sub_product, process_type, runner hints, pod overrides, ...) lives
    under ``params`` so the core model never changes to carry a new attribute.
    """

    flow: NldEntityReference[DataFlowDefinition]
    params: dict[str, Any] = Field(default_factory=dict)
    environments: dict[str, EnvironmentScheduling] = Field(default_factory=dict)

    def for_environment(self, environment: str) -> EnvironmentScheduling | None:
        """Return the scheduling config for an environment, or None if absent."""
        return self.environments.get(environment)

    def is_active_in(self, environment: str) -> bool:
        """Whether the flow is scheduled (present, enabled, triggered) in an env."""
        env_scheduling = self.for_environment(environment)
        return bool(
            env_scheduling and env_scheduling.enabled and env_scheduling.trigger
        )

    def merged_params(self, environment: str) -> dict[str, Any]:
        """Return flow-level params overlaid with the environment's params."""
        env_scheduling = self.for_environment(environment)
        if env_scheduling is None:
            return dict(self.params)
        return {**self.params, **env_scheduling.params}


class NamespacedFlowSchedulingModel(NldNamespacedBaseModelWrapper[FlowScheduling]):
    """FlowScheduling wrapped with namespace information."""


# Resolve the FlowPrecondition -> FlowScheduling forward reference now that
# FlowScheduling is defined (preconditions reference upstream schedulings).
FlowPrecondition.model_rebuild(
    _types_namespace={
        "NldEntityReference": NldEntityReference,
        "FlowScheduling": FlowScheduling,
    },
)
FlowTrigger.model_rebuild()
