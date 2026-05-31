from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nld.structure.deploy.structure_diff import (
    CharacterisationDiff,
    DiffAction,
    FieldDiff,
    StructureDiff,
)
from nld.structure.field.field import Field
from nld.structure.structure.structure import Structure
from nld.structure.structure.structure_characterisation import (
    StructureCharacterisation,
)
from nld.structure.structure.structure_characterisation_def import (
    StructureCharacterisationDefinitionNames,
)

if TYPE_CHECKING:
    from nld.connector.base import ConnectorStructureReader

COMPARABLE_CHARACTERISATION_TYPES = {
    StructureCharacterisationDefinitionNames.INDEX,
    StructureCharacterisationDefinitionNames.PRIMARY_KEY,
    StructureCharacterisationDefinitionNames.UNIQUE,
}


class StructureDiffComputer:
    """Compares a desired Structure against a current Structure.

    Produces a StructureDiff describing field-level and
    characterisation-level differences.
    """

    def compute_from_database(
        self,
        structure: Structure,
        reader: ConnectorStructureReader[Any],
        schema_name: str,
    ) -> StructureDiff:
        """Extract the current structure from DB and compute the diff."""
        current_structures = reader.extract_structures(
            schema=schema_name,
            object_name=structure.name,
        )
        current = current_structures[0] if current_structures else None
        return self.compute(
            desired=structure,
            current=current,
        )

    def compute(
        self,
        desired: Structure,
        current: Structure | None,
    ) -> StructureDiff:
        """Compute the diff between desired and current structures.

        Args:
            desired: The target structure definition from YAML.
            current: The current structure from the database,
                or None if the table does not exist.

        Returns:
            StructureDiff with all detected differences.
        """
        if current is None:
            return StructureDiff(
                structure_name=desired.name,
                table_exists=False,
            )

        field_diffs = self._compute_field_diffs(
            desired=desired,
            current=current,
        )
        characterisation_diffs = self._compute_characterisation_diffs(
            desired=desired,
            current=current,
        )
        return StructureDiff(
            structure_name=desired.name,
            table_exists=True,
            field_diffs=field_diffs,
            characterisation_diffs=characterisation_diffs,
        )

    def _compute_field_diffs(
        self,
        desired: Structure,
        current: Structure,
    ) -> list[FieldDiff]:
        """Compare fields by name and detect ADD, DROP, MODIFY actions.

        Uses get_all_fields() to include template-inherited fields
        in the comparison. Primary key fields are implicitly treated
        as non-nullable since PostgreSQL enforces NOT NULL on them.
        """
        diffs: list[FieldDiff] = []
        desired_fields = {field.name: field for field in desired.get_all_fields()}
        current_fields = {field.name: field for field in current.get_all_fields()}
        desired_names = set(desired_fields.keys())
        current_names = set(current_fields.keys())

        pk_characterisation = desired.get_characterisation(
            StructureCharacterisationDefinitionNames.PRIMARY_KEY,
        )
        pk_field_names: set[str] = (
            set(pk_characterisation.linked_fields)
            if pk_characterisation is not None
            and pk_characterisation.linked_fields is not None
            else set()
        )

        for field_name in sorted(desired_names - current_names):
            diffs.append(
                FieldDiff(
                    action=DiffAction.ADD,
                    field_name=field_name,
                )
            )

        for field_name in sorted(current_names - desired_names):
            diffs.append(
                FieldDiff(
                    action=DiffAction.DROP,
                    field_name=field_name,
                )
            )

        for field_name in sorted(desired_names & current_names):
            field_diff = self._compare_field(
                desired=desired_fields[field_name],
                current=current_fields[field_name],
                is_primary_key=field_name in pk_field_names,
            )
            if field_diff is not None:
                diffs.append(field_diff)

        return diffs

    def _compare_field(
        self,
        desired: Field,
        current: Field,
        is_primary_key: bool = False,
    ) -> FieldDiff | None:
        """Compare two fields and return a MODIFY diff if they differ.

        Args:
            desired: The target field definition from YAML.
            current: The current field from the database.
            is_primary_key: When True, the desired field is treated
                as non-nullable regardless of its mandatory
                characterisation, since PK columns are always NOT NULL.
        """
        desired_type = desired.data_type.upper()
        current_type = current.data_type.upper()
        desired_nullable = False if is_primary_key else not desired.is_mandatory()
        current_nullable = not current.is_mandatory()

        has_type_change = desired_type != current_type
        has_length_change = desired.length != current.length
        has_precision_change = desired.precision != current.precision
        has_nullable_change = desired_nullable != current_nullable

        if not any(
            [
                has_type_change,
                has_length_change,
                has_precision_change,
                has_nullable_change,
            ]
        ):
            return None

        return FieldDiff(
            action=DiffAction.MODIFY,
            field_name=desired.name,
            data_type_from=current_type if has_type_change else None,
            data_type_to=desired_type if has_type_change else None,
            length_from=current.length if has_length_change else None,
            length_to=desired.length if has_length_change else None,
            precision_from=current.precision if has_precision_change else None,
            precision_to=desired.precision if has_precision_change else None,
            nullable_from=current_nullable if has_nullable_change else None,
            nullable_to=desired_nullable if has_nullable_change else None,
        )

    def _compute_characterisation_diffs(
        self,
        desired: Structure,
        current: Structure,
    ) -> list[CharacterisationDiff]:
        """Compare structure-level characterisations (INDEX, PRIMARY_KEY, UNIQUE)."""
        diffs: list[CharacterisationDiff] = []

        desired_map = self._build_characterisation_map(desired.characterisations)
        current_map = self._build_characterisation_map(current.characterisations)

        desired_keys = set(desired_map.keys())
        current_keys = set(current_map.keys())

        for key in sorted(desired_keys - current_keys):
            char_type, constraint_name = key
            desired_char = desired_map[key]
            diffs.append(
                CharacterisationDiff(
                    action=DiffAction.ADD,
                    characterisation_type=char_type,
                    constraint_name=constraint_name,
                    linked_fields_to=desired_char.linked_fields,
                )
            )

        for key in sorted(current_keys - desired_keys):
            char_type, constraint_name = key
            current_char = current_map[key]
            diffs.append(
                CharacterisationDiff(
                    action=DiffAction.DROP,
                    characterisation_type=char_type,
                    constraint_name=constraint_name,
                    linked_fields_from=current_char.linked_fields,
                )
            )

        for key in sorted(desired_keys & current_keys):
            char_type, constraint_name = key
            desired_char = desired_map[key]
            current_char = current_map[key]
            desired_fields = sorted(desired_char.linked_fields or [])
            current_fields = sorted(current_char.linked_fields or [])
            if desired_fields != current_fields:
                diffs.append(
                    CharacterisationDiff(
                        action=DiffAction.MODIFY,
                        characterisation_type=char_type,
                        constraint_name=constraint_name,
                        linked_fields_from=current_char.linked_fields,
                        linked_fields_to=desired_char.linked_fields,
                    )
                )

        return diffs

    def _build_characterisation_map(
        self,
        characterisations: list[StructureCharacterisation],
    ) -> dict[tuple[str, str], StructureCharacterisation]:
        """Build a lookup map keyed by (characterisation_type, name).

        Only includes characterisation types relevant for deploy
        comparison (INDEX, PRIMARY_KEY, UNIQUE).
        """
        result: dict[tuple[str, str], StructureCharacterisation] = {}
        for char in characterisations:
            if char.characterisation in COMPARABLE_CHARACTERISATION_TYPES:
                result[(char.characterisation, char.name)] = char
        return result
