from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field, model_validator

from nld.pydantic import NldBaseModel, NldEntityReference

if TYPE_CHECKING:
    from nld.scheduling.models.scheduling import FlowTask

SchedulingExecutionState = Literal[
    "SUCCESS",
    "WARNING",
    "FAILED",
    "KILLED",
    "CANCELLED",
]

_DEFAULT_PRECONDITION_STATES: list[SchedulingExecutionState] = ["SUCCESS", "WARNING"]


class FlowPrecondition(NldBaseModel):
    """An upstream task that must reach a terminal state before this runs.

    ``name`` references another FlowTask entity — a task's trigger can depend
    on another task's outcome.

    When ``external`` is False (the default) the reference is resolved against
    the local registry and a dangling predecessor is a load-time error. When
    ``external`` is True the upstream task lives in another data product;
    the reference is informational only and is neither resolved nor validated
    locally (a single data product cannot see another product's registry).

    For an external predecessor, ``name`` is the bare entity name and
    ``nld_project`` identifies the upstream data product (its nld project name).
    The cross-product identity is intentionally expressed in nld terms, not in a
    platform-specific namespace: consumers (e.g. a Kestra scheduling generator)
    resolve ``nld_project`` to whatever namespace their platform uses.
    """

    name: "NldEntityReference[FlowTask]"
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
    """Event-based trigger: runs after upstream tasks complete.

    ``predecessors`` fully overrides the automatic lineage: when it is
    non-empty, the flow dependency graph is never consulted, and the
    upstream set is exactly ``get_all_predecessors()`` (``predecessors`` +
    ``additional_predecessors``, net of ``excluded_predecessors``). Use it
    when a task's upstream set should not track the flow's own
    dependencies.

    When ``predecessors`` is empty, the resolver derives the automatic
    lineage from the flow dependency graph and adds ``get_all_predecessors()``
    (``additional_predecessors``, net of ``excluded_predecessors``) on top of
    it — the additive/subtractive mode.
    """

    kind: Literal["flow"]
    predecessors: list[FlowPrecondition] = Field(default_factory=list)
    additional_predecessors: list[FlowPrecondition] = Field(default_factory=list)
    excluded_predecessors: list[FlowPrecondition] = Field(default_factory=list)

    def get_all_predecessors(self) -> list[FlowPrecondition]:
        """Return ``predecessors``/``additional_predecessors``, net of exclusions.

        Combines ``predecessors`` and ``additional_predecessors``, then drops
        any entry that also appears in ``excluded_predecessors`` (matched on
        ``name``, ``external``, and ``nld_project``).
        """
        excluded_keys = {
            (excluded.name, excluded.external, excluded.nld_project)
            for excluded in self.excluded_predecessors
        }
        return [
            predecessor
            for predecessor in [*self.predecessors, *self.additional_predecessors]
            if (predecessor.name, predecessor.external, predecessor.nld_project)
            not in excluded_keys
        ]


Trigger = Annotated[
    ScheduleTrigger | FlowTrigger,
    Field(discriminator="kind"),
]
