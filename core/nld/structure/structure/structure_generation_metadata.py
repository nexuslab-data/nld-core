from pydantic import Field as PydanticField

from nld.pydantic import NldBaseModel


class StructureGenerationMetadata(NldBaseModel):
    """Provenance of a structure generated from its flow's single predecessor.

    Written by ``nld structure generate`` into the structure YAML. It marks
    the structure as generated and names the flow to regenerate it from, so
    a stale structure is detected by regenerating it in memory and comparing
    the result with the file.
    """

    flow: str = PydanticField(
        description="Flow whose target this structure is: <namespace>.<flow_name>",
    )
    source: str = PydanticField(
        description="Source structure: <namespace>.<structure_name>",
    )
