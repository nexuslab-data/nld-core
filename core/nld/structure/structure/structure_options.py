from enum import StrEnum, auto

from nld.pydantic import NldBaseModel


class StructureOptionDefinition(NldBaseModel):
    name: str
    description: str


class StructureOptionNames(StrEnum):
    FILE_FORMAT = auto()


class StructureOptionDefinitions:
    """Generic constraints"""

    FILE_FORMAT = StructureOptionDefinition(
        name=StructureOptionNames.FILE_FORMAT.name,
        description="The file format",
    )
