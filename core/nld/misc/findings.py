from pydantic import Field

from nld.pydantic import NldBaseModel


class FindingSeverity:
    """Severity tokens shared by every validation finding."""

    ERROR = "error"
    INFO = "info"
    WARNING = "warning"


class ValidationFinding(NldBaseModel):
    """Base model for a single validation finding produced when checking an entity.

    A finding carries enough context to render a friendly line or a
    machine-readable payload: which entity it belongs to, a human message and a
    severity. Concrete checks subclass this to add their own locating attributes
    (a field name, an audited column, a link, ...) and override ``get_subject``
    to point at them.
    """

    entity: str = Field(
        description="Identifier of the entity the finding belongs to",
    )
    message: str = Field(
        description="Human-readable explanation of the finding",
    )
    severity: str = Field(
        default=FindingSeverity.ERROR,
        description="Severity of the finding",
    )

    def get_subject(self) -> str:
        """Return the most specific locus of the finding; entity by default."""
        return self.entity

    def render_line(self) -> str:
        """Render a friendly one-line representation of the finding."""
        return f"{self.get_subject()}: {self.message}"
