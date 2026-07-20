from typing import Any

from pydantic import Field, field_validator

from nld.misc import ValidationFinding
from nld.pydantic import (
    NldEntityReference,
    NldNamedBaseModel,
    NldNamespacedBaseModelWrapper,
)
from nld.structure.structure.structure import Structure

from .audit_column import AuditColumn
from .audit_metadata import AuditMetadata
from .audit_target import AuditTarget


class StructureAuditValidationFinding(ValidationFinding):
    """A single structure audit validation finding.

    Adds the audited column on top of the shared ValidationFinding context;
    ``entity`` holds the audited structure name.
    """

    column: str = Field(
        description="Name of the audited column the finding is about",
    )

    def get_subject(self) -> str:
        """Locate the finding on its audited column."""
        return self.column


class StructureAudit(NldNamedBaseModel):
    """A standardised, machine-readable data analysis audit of one structure.

    Captures the *measured* facts about a structure at a point in time: its
    target environment, run metadata (sampling, date coverage), and a per-column
    listing carrying coverage and the column's value distribution.
    Field-selection decisions are intentionally excluded; those are an agent
    judgement, not a measurement.

    Naming convention: an audit's name (and its file stem) is the audited
    structure name, with no version suffix. Production is the audited-by-default
    reference, so a prd audit keeps the bare structure name
    (``raw_web_hr_wttj_jobs``); a non-production audit appends its environment
    (``raw_web_hr_wttj_jobs_dev``).

    Example YAML:
        name: raw_web_hr_wttj_jobs
        description: Data analysis audit of the WTTJ jobs raw table
        structure: wttj.raw_web_hr_wttj_jobs
        target:
            environment: prd
            schema: acquisition_web_hr
            table: raw_web_hr_wttj_jobs
        metadata:
            audited_at: 2026-04-04T00:00:00
            layer: raw
            row_count: 1251
        columns:
            contract_type:
                data_type: CHARACTER VARYING
                nullable: false
                coverage: { non_null: 1251, pct: 100.0, distinct: 8 }
                distribution:
                    top_n: 10
                    truncated: false
                    values:
                        - { value: full_time, count: 884, pct: 70.7 }
    """

    description: str | None = Field(
        default=None,
        description="Description of the audit",
    )
    structure: NldEntityReference[Structure] = Field(
        description="Reference to the audited structure (namespace.name)",
    )
    target: AuditTarget = Field(
        description="Environment and physical location the audit was run against",
    )
    metadata: AuditMetadata = Field(
        default_factory=AuditMetadata,
        description="Run provenance: sampling, date coverage, row count",
    )
    columns: dict[str, AuditColumn] = Field(
        default={},
        description="Per-column listing, coverage and distribution (ordinal order)",
    )

    @field_validator("columns", mode="before")
    @classmethod
    def set_names_from_keys(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Sets each column's name from its dict key when missing."""
        if value is None:
            return {}
        for key, entry in value.items():
            if isinstance(entry, dict):
                entry.setdefault("name", key)
            elif isinstance(entry, AuditColumn) and entry.name != key:
                entry.name = key
        return value

    def get_column(self, name: str) -> AuditColumn:
        """Returns an audited column by name."""
        if name not in self.columns:
            raise KeyError(f"Column '{name}' not found in audit '{self.name}'")
        return self.columns[name]

    def get_columns(self) -> list[AuditColumn]:
        """Returns all audited columns as a list, in defined order."""
        return list(self.columns.values())

    def get_column_names(self) -> list[str]:
        """Returns all audited column names."""
        return list(self.columns.keys())

    def has_column(self, name: str) -> bool:
        """Checks whether a column was audited."""
        return name in self.columns

    def get_columns_with_distribution(self) -> list[AuditColumn]:
        """Returns the audited columns that carry a value distribution."""
        return [col for col in self.get_columns() if col.distribution is not None]

    def validate_columns(self) -> list[StructureAuditValidationFinding]:
        """Validates audited columns against the referenced structure.

        Resolves the referenced structure and checks that every audited column
        is an actual field of that structure. Requires an active
        NldExecutionContext with a loaded entity registry.

        Returns:
            The list of findings; empty when every audited column is valid.
        """
        from nld.service.nld_entity_registry import EntityTypeNames

        findings: list[StructureAuditValidationFinding] = []
        structure = self.structure.resolve(
            entity_type=EntityTypeNames.STRUCTURE,
        )
        field_names = structure.get_field_names()

        for column_name in self.columns:
            if column_name not in field_names:
                findings.append(
                    StructureAuditValidationFinding(
                        entity=self.name,
                        column=column_name,
                        message=(
                            f"Audited column '{column_name}' not found in "
                            f"structure '{structure.name}'"
                        ),
                    )
                )
        return findings


class NamespacedStructureAudit(NldNamespacedBaseModelWrapper["StructureAudit"]):
    """StructureAudit wrapped with namespace information."""
