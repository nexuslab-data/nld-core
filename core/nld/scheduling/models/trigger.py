from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field, model_validator

from nld.pydantic import NldBaseModel, NldEntityReference

if TYPE_CHECKING:
    from nld.scheduling.models.scheduling import FlowScheduling

SchedulingExecutionState = Literal[
    "SUCCESS",
    "WARNING",
    "FAILED",
    "KILLED",
    "CANCELLED",
]

_DEFAULT_PRECONDITION_STATES: list[SchedulingExecutionState] = ["SUCCESS", "WARNING"]


class FlowPrecondition(NldBaseModel):
    """An upstream scheduling that must reach a terminal state before this runs.

    ``name`` references another FlowScheduling entity (the scheduled task), so
    scheduling depends on scheduling.

    When ``external`` is False (the default) the reference is resolved against
    the local registry and a dangling predecessor is a load-time error. When
    ``external`` is True the upstream scheduling lives in another data product;
    the reference is informational only and is neither resolved nor validated
    locally (a single data product cannot see another product's registry).

    For an external predecessor, ``name`` is the bare entity name and
    ``nld_project`` identifies the upstream data product (its nld project name).
    The cross-product identity is intentionally expressed in nld terms, not in a
    platform-specific namespace: consumers (e.g. a Kestra scheduling generator)
    resolve ``nld_project`` to whatever namespace their platform uses.
    """

    name: "NldEntityReference[FlowScheduling]"
    external: bool = False
    nld_project: str | None = None
    states: list[SchedulingExecutionState] = Field(
        default_factory=lambda: list(_DEFAULT_PRECONDITION_STATES),
        min_length=1,
    )

    @model_validator(mode="after")
    def _validate_nld_project(self) -> "FlowPrecondition":
        if self.nld_project is not None and not self.external:
            raise ValueError(
                "nld_project is only valid on an external predecessor (external: true)"
            )
        return self


class ScheduleTrigger(NldBaseModel):
    """Time-based trigger: a single cron for the environment it is declared in."""

    kind: Literal["schedule"]
    cron: str


class FlowTrigger(NldBaseModel):
    """Event-based trigger: runs after upstream schedulings complete.

    When ``predecessors`` is empty, the resolver derives them from the flow
    dependency graph. An explicit list overrides the derivation.
    """

    kind: Literal["flow"]
    predecessors: list[FlowPrecondition] = Field(default_factory=list)


Trigger = Annotated[
    ScheduleTrigger | FlowTrigger,
    Field(discriminator="kind"),
]
