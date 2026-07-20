from nld.pydantic.base_model import NldBaseModel
from nld.utils import NldStrEnum


class DiffAction(NldStrEnum):
    ADD = "ADD"
    DROP = "DROP"
    MODIFY = "MODIFY"


class FieldDiff(NldBaseModel):
    """Describes a single field-level difference between two structures."""

    action: DiffAction
    field_name: str
    data_type_from: str | None = None
    data_type_to: str | None = None
    default_from: str | None = None
    default_to: str | None = None
    length_from: int | None = None
    length_to: int | None = None
    precision_from: int | None = None
    precision_to: int | None = None
    nullable_from: bool | None = None
    nullable_to: bool | None = None


class CharacterisationDiff(NldBaseModel):
    """Describes a single structure-level characterisation difference."""

    action: DiffAction
    characterisation_type: str
    constraint_name: str
    linked_fields_from: list[str] | None = None
    linked_fields_to: list[str] | None = None


class StructureDiff(NldBaseModel):
    """Aggregates all differences between a desired and current structure."""

    structure_name: str
    table_exists: bool
    field_diffs: list[FieldDiff] = []
    characterisation_diffs: list[CharacterisationDiff] = []
    order_mismatch: bool = False

    def has_changes(self) -> bool:
        """Return True if the table is new or any differences exist."""
        return (
            not self.table_exists
            or len(self.field_diffs) > 0
            or len(self.characterisation_diffs) > 0
            or self.order_mismatch
        )

    def is_new_table(self) -> bool:
        """Return True if the table does not exist in the database."""
        return not self.table_exists
