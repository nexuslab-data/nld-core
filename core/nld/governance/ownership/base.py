from pydantic import Field as PydanticField

from nld.pydantic import NldNamedBaseModel


class OwnerBase(NldNamedBaseModel):
    """Common shape for an ownership declaration.

    The accountable party is a ``team``; ``contact`` is an escalation channel
    (slack/email) and ``description`` documents the scope of the responsibility.
    Concrete subclasses split the two distinct accountabilities a structure has:
    its data (``StructureOwner``) and its technical execution (``FlowOwner``).

    A declaration is the **namespace default** when ``targets`` is omitted: it
    applies to every entity beneath its namespace. When ``targets`` is set, the
    declaration is a **per-entity override** that applies only to the named
    structures (or flows) — and a matching override always wins over the
    namespace default.
    """

    team: str = PydanticField(
        description="Name of the accountable team",
    )
    contact: str | None = PydanticField(
        default=None,
        description="Escalation channel for this team (e.g. a slack channel or email)",
    )
    description: str | None = PydanticField(
        default=None,
        description="What this ownership covers",
    )
    targets: list[str] | None = PydanticField(
        default=None,
        description="Specific structure/flow names this declaration applies to; "
        "when omitted, it is the namespace default applying to every entity beneath",
    )
