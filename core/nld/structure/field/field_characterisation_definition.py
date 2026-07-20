from pydantic import Field

from nld.pydantic import NldNamedBaseModel, NldNamespacedBaseModelWrapper
from nld.utils import NldStrEnum


class FieldCharacterisationType(NldNamedBaseModel):
    pass


class FieldCharacterisationDefinition(NldNamedBaseModel):
    description: str = Field(
        description="Description of this characterisation definition",
    )
    allowed_attributes: list[str] | None = Field(
        default=None,
        description="List of allowed attributes for this characterisation",
    )
    applicable_to_single_field_per_structure: bool = Field(
        default=True,
        description=(
            "Whether this characterisation can only be applied to one field "
            "per structure"
        ),
    )


class FieldCharacterisationDefinitionAttributesNames(NldStrEnum):
    """Default Field Characterisation Names"""

    ENFORCED = "enforced"


class FieldCharacterisationDefinitionNames(NldStrEnum):
    MANDATORY = "mandatory"
    UNIQUE = "unique"

    REC_PREVIOUS_LAYER_UPDATE_TST = "rec_previous_layer_update_tst"
    REC_INSERT_TST = "rec_insert_tst"
    REC_LAST_UPDATE_TST = "rec_last_update_tst"

    REC_SOURCE_EXTRACTION_TST = "rec_source_extraction_tst"
    REC_SOURCE_INSERT_TST = "rec_source_insert_tst"
    REC_SOURCE_LAST_UPDATE_TST = "rec_source_last_update_tst"

    REC_DELETION_FLAG = "rec_deletion_flag"
    REC_DELETION_TST = "rec_deletion_tst"
    REC_DELETION_BY = "rec_deletion_by"

    EXCLUDE_FROM_UPSERT_MATCH = "exclude_from_upsert_match"
    EXCLUDE_FROM_UPSERT_UPDATE = "exclude_from_upsert_update"


class FieldCharacterisationDefinitions:
    """Field Characterisation common definitions"""

    """Generic constraints"""
    MANDATORY = FieldCharacterisationDefinition(
        name=FieldCharacterisationDefinitionNames.MANDATORY.name,
        description="Field is mandatory",
        allowed_attributes=[FieldCharacterisationDefinitionAttributesNames.ENFORCED],
        applicable_to_single_field_per_structure=False,
    )
    UNIQUE = FieldCharacterisationDefinition(
        name=FieldCharacterisationDefinitionNames.UNIQUE.name,
        description="Content of the field is unique",
        allowed_attributes=[FieldCharacterisationDefinitionAttributesNames.ENFORCED],
        applicable_to_single_field_per_structure=False,
    )

    """Record Technical Characterisations - General information on data changes"""
    REC_INSERT_TST = FieldCharacterisationDefinition(
        name=FieldCharacterisationDefinitionNames.REC_INSERT_TST.name,
        description=(
            "Record Technical Characterisation - Timestamp of first insertion "
            "in the current structure"
        ),
        applicable_to_single_field_per_structure=True,
    )
    REC_LAST_UPDATE_TST = FieldCharacterisationDefinition(
        name=FieldCharacterisationDefinitionNames.REC_LAST_UPDATE_TST.name,
        description=(
            "Record Technical Characterisation - Timestamp of last update "
            "in the current structure"
        ),
        applicable_to_single_field_per_structure=True,
    )
    """ Record Technical Characterisations - Logical deletion flag """
    REC_DELETION_FLAG = FieldCharacterisationDefinition(
        name=FieldCharacterisationDefinitionNames.REC_DELETION_FLAG.name,
        description=(
            "Record Technical Characterisation - Deletion Flag "
            "(1 means logically deleted, 0 means active)"
        ),
        applicable_to_single_field_per_structure=True,
    )
    REC_DELETION_TST = FieldCharacterisationDefinition(
        name=FieldCharacterisationDefinitionNames.REC_DELETION_TST.name,
        description=(
            "Record Technical Characterisation - Timestamp of the deletion "
            "in the current structure"
        ),
        applicable_to_single_field_per_structure=True,
    )
    REC_DELETION_BY = FieldCharacterisationDefinition(
        name=FieldCharacterisationDefinitionNames.REC_DELETION_BY.name,
        description=(
            "Record Technical Characterisation - User that applied the "
            "deletion in the current structure"
        ),
        applicable_to_single_field_per_structure=True,
    )
    """Upsert behavior characterisations"""
    EXCLUDE_FROM_UPSERT_MATCH = FieldCharacterisationDefinition(
        name=FieldCharacterisationDefinitionNames.EXCLUDE_FROM_UPSERT_MATCH.name,
        description=(
            "Field is updated on upsert but excluded from change "
            "detection (IS DISTINCT FROM check)"
        ),
        applicable_to_single_field_per_structure=False,
    )
    EXCLUDE_FROM_UPSERT_UPDATE = FieldCharacterisationDefinition(
        name=FieldCharacterisationDefinitionNames.EXCLUDE_FROM_UPSERT_UPDATE.name,
        description=(
            "Field is excluded from both UPDATE SET and change "
            "detection on upsert (insert-only field)"
        ),
        applicable_to_single_field_per_structure=False,
    )

    """Record Technical Characterisations - General Source information
    (insert, update, deletion and archival information)"""
    REC_SOURCE_INSERT_TST = FieldCharacterisationDefinition(
        name=FieldCharacterisationDefinitionNames.REC_SOURCE_INSERT_TST.name,
        description=(
            "Record Technical Characterisation - Timestamp of first insertion "
            "in source structure"
        ),
        allowed_attributes=[],
        applicable_to_single_field_per_structure=True,
    )
    REC_SOURCE_LAST_UPDATE_TST = FieldCharacterisationDefinition(
        name=FieldCharacterisationDefinitionNames.REC_SOURCE_LAST_UPDATE_TST.name,
        description=(
            "Record Technical Characterisation - Timestamp of last update "
            "in source structure"
        ),
        allowed_attributes=[],
        applicable_to_single_field_per_structure=True,
    )
    REC_SOURCE_EXTRACTION_TST = FieldCharacterisationDefinition(
        name=FieldCharacterisationDefinitionNames.REC_SOURCE_EXTRACTION_TST.name,
        description=(
            "Record Technical Characterisation - Timestamp of the extraction "
            "from the source"
        ),
        allowed_attributes=[],
        applicable_to_single_field_per_structure=True,
    )
    REC_PREVIOUS_LAYER_UPDATE_TST = FieldCharacterisationDefinition(
        name=FieldCharacterisationDefinitionNames.REC_PREVIOUS_LAYER_UPDATE_TST.name,
        description=(
            "Record Technical Characterisation - Timestamp of last update "
            "in the previous layer"
        ),
        allowed_attributes=[],
        applicable_to_single_field_per_structure=True,
    )


# Built-in catalogue of code default definitions, keyed by the lowercase
# characterisation token actually stored on fields (FieldCharacterisation
# lowercases its ``characterisation``). Built by collecting every real
# FieldCharacterisationDefinition declared on FieldCharacterisationDefinitions.
FIELD_CHARACTERISATION_DEFINITIONS: dict[str, FieldCharacterisationDefinition] = {
    definition.name.lower(): definition
    for definition in vars(FieldCharacterisationDefinitions).values()
    if isinstance(definition, FieldCharacterisationDefinition)
}


class NamespacedFieldCharacterisationDefinition(
    NldNamespacedBaseModelWrapper["FieldCharacterisationDefinition"],
):
    """FieldCharacterisationDefinition wrapped with namespace information."""
