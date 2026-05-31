from nld.pydantic import NldBaseModel
from nld.utils import NldStrEnum


class StructureCharacterisationDefinition(NldBaseModel):
    name: str
    description: str
    allowed_attributes: list[str] | None
    linked_to_fields: bool = True
    allowed_multiple_characterisations_per_structure: bool = False


class StructureCharacterisationDefinitionAttributesNames(NldStrEnum):
    ENFORCED = "enforced"


class StructureCharacterisationDefinitionNames(NldStrEnum):
    PRIMARY_KEY = "primary_key"
    TECHNICAL_UNIQUE_KEY = "technical_unique_key"
    FUNCTIONAL_UNIQUE_KEY = "functional_unique_key"
    FUNCTIONAL_KEY = "functional_key"
    INDEX = "index"
    UNIQUE = "unique"


class StructureCharacterisationDefinitions:
    PRIMARY_KEY = StructureCharacterisationDefinition(
        name=StructureCharacterisationDefinitionNames.PRIMARY_KEY.value,
        description="Primary Key",
        allowed_attributes=[
            StructureCharacterisationDefinitionAttributesNames.ENFORCED
        ],
        linked_to_fields=True,
        allowed_multiple_characterisations_per_structure=False,
    )
    TECHNICAL_UNIQUE_KEY = StructureCharacterisationDefinition(
        name=StructureCharacterisationDefinitionNames.TECHNICAL_UNIQUE_KEY.value,
        description=(
            "Technical Unique Key, defines record uniqueness based on "
            "the fields linked to this technical key"
        ),
        allowed_attributes=[],
        linked_to_fields=True,
        allowed_multiple_characterisations_per_structure=False,
    )
    FUNCTIONAL_UNIQUE_KEY = StructureCharacterisationDefinition(
        name=StructureCharacterisationDefinitionNames.FUNCTIONAL_UNIQUE_KEY.value,
        description=(
            "Functional Unique Key, defines record uniqueness based on "
            "the fields linked to this functional key"
        ),
        allowed_attributes=[],
        linked_to_fields=True,
        allowed_multiple_characterisations_per_structure=False,
    )
    FUNCTIONAL_KEY = StructureCharacterisationDefinition(
        name=StructureCharacterisationDefinitionNames.FUNCTIONAL_KEY.value,
        description=(
            "Functional Key, defines record uniqueness based on "
            "the fields linked to this functional key"
        ),
        allowed_attributes=[],
        linked_to_fields=True,
        allowed_multiple_characterisations_per_structure=False,
    )
    INDEX = StructureCharacterisationDefinition(
        name=StructureCharacterisationDefinitionNames.INDEX.value,
        description="Non-unique index on the list of fields",
        allowed_attributes=[],
        linked_to_fields=True,
        allowed_multiple_characterisations_per_structure=True,
    )
    UNIQUE = StructureCharacterisationDefinition(
        name=StructureCharacterisationDefinitionNames.UNIQUE.value,
        description="Uniqueness of records of the list of fields",
        allowed_attributes=[],
        linked_to_fields=True,
        allowed_multiple_characterisations_per_structure=True,
    )


STRUCTURE_CHARACTERISATION_DEFINITIONS: dict[
    str, StructureCharacterisationDefinition
] = {
    StructureCharacterisationDefinitions.FUNCTIONAL_UNIQUE_KEY.name: (
        StructureCharacterisationDefinitions.FUNCTIONAL_UNIQUE_KEY
    ),
    StructureCharacterisationDefinitions.INDEX.name: (
        StructureCharacterisationDefinitions.INDEX
    ),
    StructureCharacterisationDefinitions.PRIMARY_KEY.name: (
        StructureCharacterisationDefinitions.PRIMARY_KEY
    ),
    StructureCharacterisationDefinitions.TECHNICAL_UNIQUE_KEY.name: (
        StructureCharacterisationDefinitions.TECHNICAL_UNIQUE_KEY
    ),
    StructureCharacterisationDefinitions.UNIQUE.name: (
        StructureCharacterisationDefinitions.UNIQUE
    ),
}
