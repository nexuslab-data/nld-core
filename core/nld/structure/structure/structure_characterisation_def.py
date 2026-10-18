from nld.logging import log_warn_default
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
    BUSINESS_UNIQUE_KEY = "business_unique_key"
    BUSINESS_KEY = "business_key"
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
    BUSINESS_UNIQUE_KEY = StructureCharacterisationDefinition(
        name=StructureCharacterisationDefinitionNames.BUSINESS_UNIQUE_KEY.value,
        description=(
            "Business Unique Key, defines record uniqueness based on "
            "the fields linked to this business key"
        ),
        allowed_attributes=[],
        linked_to_fields=True,
        allowed_multiple_characterisations_per_structure=False,
    )
    BUSINESS_KEY = StructureCharacterisationDefinition(
        name=StructureCharacterisationDefinitionNames.BUSINESS_KEY.value,
        description=(
            "Business Key (non-unique), identifies the business entity "
            "through the fields linked to this business key"
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
    StructureCharacterisationDefinitions.BUSINESS_KEY.name: (
        StructureCharacterisationDefinitions.BUSINESS_KEY
    ),
    StructureCharacterisationDefinitions.BUSINESS_UNIQUE_KEY.name: (
        StructureCharacterisationDefinitions.BUSINESS_UNIQUE_KEY
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

DEPRECATED_STRUCTURE_CHARACTERISATION_ALIASES: dict[str, str] = {
    "functional_key": StructureCharacterisationDefinitionNames.BUSINESS_KEY.value,
    "functional_unique_key": (
        StructureCharacterisationDefinitionNames.BUSINESS_UNIQUE_KEY.value
    ),
}


def resolve_structure_characterisation_alias(
    characterisation: str,
    location: str,
) -> str:
    """Map a deprecated structure characterisation to its canonical name.

    The ``functional_*`` names were renamed ``business_*``; the old names
    stay accepted until a future release so existing structure YAMLs keep
    loading, but every use logs a warning pointing at ``location``.

    Example:
        >>> resolve_structure_characterisation_alias(
        ...     "functional_key",
        ...     location="'fk_my_table' (structure/my_table.yml)",
        ... )
        'business_key'
    """
    canonical_name = DEPRECATED_STRUCTURE_CHARACTERISATION_ALIASES.get(
        characterisation,
    )
    if canonical_name is None:
        return characterisation
    log_warn_default(
        f"Deprecated structure characterisation '{characterisation}' in "
        f"{location}, rename it to '{canonical_name}': the old name will be "
        f"removed in a future release",
    )
    return canonical_name
