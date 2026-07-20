from __future__ import annotations

from nld.connector.base.deploy_capabilities import (
    ConnectorDeployCapabilities,
    normalize_comparable_data_type,
)
from nld.exceptions import NldRuntimeException
from nld.pydantic.base_model import NldBaseModel
from nld.structure.deploy.structure_schema_history import (
    StructureSchemaSnapshot,
    StructureSchemaSnapshotField,
)


class DeploymentDriftError(NldRuntimeException):
    """Raised when the live schema drifted outside the intended change."""


class DriftReport(NldBaseModel):
    """Classification of the live schema against the recorded state.

    Drift = differences between the actual schema (A) and the
    recorded state (R). A difference is expected when the intended
    change (D − R) accounts for it; anything else is unexpected and
    refuses the deploy by default.
    """

    structure_name: str
    table_missing: bool = False
    drifted_field_names: list[str] = []
    unexpected_field_details: dict[str, str] = {}
    unexpected_field_names: list[str] = []

    def has_unexpected_drift(self) -> bool:
        """Return True when the drift is not explained by the intended change."""
        return self.table_missing or len(self.unexpected_field_names) > 0

    def build_error_message(self) -> str:
        """Build the precise refusal message for the deploy."""
        if self.table_missing:
            return (
                f"Structure '{self.structure_name}': the recorded table is "
                "missing from the target database — it was dropped outside "
                "nld. Re-create it, or re-run with --adopt / --rebuild / "
                "--allow-drift."
            )
        drifted = "; ".join(
            f"{name} ({self.unexpected_field_details.get(name, 'changed')})"
            for name in self.unexpected_field_names
        )
        return (
            f"Structure '{self.structure_name}': column(s) [{drifted}] differ "
            "from the recorded state and are not part of the intended "
            "change — the table was modified outside nld. Re-run with "
            "--adopt to accept the current state as the new baseline, "
            "--allow-drift to deploy against it anyway, or --rebuild "
            "to recreate from the asset."
        )


def _comparable_fields(
    snapshot: StructureSchemaSnapshot,
    capabilities: ConnectorDeployCapabilities | None = None,
) -> dict[str, tuple[str, int, int, bool]]:
    """Index the snapshot fields by name with their physical attributes."""

    def field_key(field: StructureSchemaSnapshotField) -> tuple[str, int, int, bool]:
        return (
            normalize_comparable_data_type(
                data_type=field.data_type,
                capabilities=capabilities,
            ),
            field.length,
            field.precision,
            field.nullable,
        )

    return {field.name: field_key(field) for field in snapshot.fields}


def _changed_field_names(
    base: StructureSchemaSnapshot,
    other: StructureSchemaSnapshot,
    capabilities: ConnectorDeployCapabilities | None = None,
) -> set[str]:
    """Return the field names added, removed or modified between snapshots."""
    base_fields = _comparable_fields(snapshot=base, capabilities=capabilities)
    other_fields = _comparable_fields(snapshot=other, capabilities=capabilities)
    changed = set(base_fields.keys()) ^ set(other_fields.keys())
    for name in set(base_fields.keys()) & set(other_fields.keys()):
        if base_fields[name] != other_fields[name]:
            changed.add(name)
    return changed


def classify_drift(
    structure_name: str,
    recorded_snapshot: StructureSchemaSnapshot,
    actual_snapshot: StructureSchemaSnapshot | None,
    desired_snapshot: StructureSchemaSnapshot,
    expected_extra_field_names: set[str] | None = None,
    capabilities: ConnectorDeployCapabilities | None = None,
) -> DriftReport:
    """Classify the A−R drift against the intended D−R change.

    Field-level classification only: a characterisation-only hash
    difference is reconciled by the deployment diff and never refuses
    the deploy. ``expected_extra_field_names`` carries the old and
    new names of pending declared renames, which are intended
    changes even though they are not visible in D−R.
    """
    if actual_snapshot is None:
        return DriftReport(
            structure_name=structure_name,
            table_missing=True,
        )

    drifted = _changed_field_names(
        base=recorded_snapshot,
        other=actual_snapshot,
        capabilities=capabilities,
    )
    expected = _changed_field_names(
        base=recorded_snapshot,
        other=desired_snapshot,
        capabilities=capabilities,
    ) | (expected_extra_field_names or set())
    unexpected = sorted(drifted - expected)

    recorded_fields = _comparable_fields(
        snapshot=recorded_snapshot,
        capabilities=capabilities,
    )
    actual_fields = _comparable_fields(
        snapshot=actual_snapshot,
        capabilities=capabilities,
    )
    unexpected_details = {
        name: (f"recorded={recorded_fields.get(name)} actual={actual_fields.get(name)}")
        for name in unexpected
    }

    return DriftReport(
        structure_name=structure_name,
        drifted_field_names=sorted(drifted),
        unexpected_field_details=unexpected_details,
        unexpected_field_names=unexpected,
    )
