# ruff: noqa: I001
# Import order is intentional to avoid circular imports
from .structure_template import NamespacedStructureTemplate, StructureTemplate
from .structure import (
    EXTERNAL_SOURCE_TAG,
    MANAGED_BY_FLOW_EXECUTION_TAG,
    NamespacedStructure,
    Structure,
)
from .structure_characterisation import (
    StructureCharacterisation,
)
from .structure_characterisation_def import (
    StructureCharacterisationDefinition,
    StructureCharacterisationDefinitionNames,
)
from .structure_definition import StructureDefinition
from .structure_generation_metadata import StructureGenerationMetadata
from .structure_referential import StructureNamespace

# StructureAdapter must be imported AFTER StructureCharacterisation
# because it depends on service.structure_characterisation_adapter
# which imports StructureCharacterisation
from .structure_adapter import NamespacedStructureAdapter, StructureAdapter

__all__ = [
    "EXTERNAL_SOURCE_TAG",
    "MANAGED_BY_FLOW_EXECUTION_TAG",
    "NamespacedStructure",
    "NamespacedStructureAdapter",
    "NamespacedStructureTemplate",
    "Structure",
    "StructureAdapter",
    "StructureCharacterisation",
    "StructureCharacterisationDefinition",
    "StructureCharacterisationDefinitionNames",
    "StructureDefinition",
    "StructureGenerationMetadata",
    "StructureNamespace",
    "StructureTemplate",
]
