from nld.structure.structure import (
    StructureCharacterisation,
)


class StructureCharacterisationAdapter:
    @classmethod
    def adapt_structure_characterisation(
        cls,
        original_structure_characterisation: StructureCharacterisation,
        target_from_source_field_naming_mapping_dict: dict[str, str],
        target_structure_name: str,
    ) -> StructureCharacterisation:
        source_to_target_field_naming_mapping_dict: dict[str, str] = dict(
            (v, k) for k, v in target_from_source_field_naming_mapping_dict.items()
        )

        linked_fields = (
            [
                source_to_target_field_naming_mapping_dict[linked_field]
                for linked_field in original_structure_characterisation.linked_fields
                if linked_field
                in list(source_to_target_field_naming_mapping_dict.keys())
            ]
            if original_structure_characterisation.linked_fields is not None
            else []
        )
        new_characterisation = StructureCharacterisation(
            characterisation=original_structure_characterisation.characterisation,
            name=f"PK_{target_structure_name}",
            linked_fields=linked_fields,
            attributes=None,
        )
        return new_characterisation
