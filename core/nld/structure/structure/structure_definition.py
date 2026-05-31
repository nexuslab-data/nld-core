from nld.pydantic import NldBaseModel


class StructureDefinition(NldBaseModel):
    name: str
    type: str
