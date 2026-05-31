from pydantic import Field as PydanticField

from nld.pydantic import NldBaseModel, NldNamedBaseModel, NldNamespacedBaseModelWrapper


class Term(NldBaseModel):
    """A single business term with synonyms, description, and cross-references."""

    name: str = PydanticField(description="Canonical term name")
    description: str = PydanticField(
        description="Detailed description of the business meaning",
    )
    synonyms: list[str] = PydanticField(
        default_factory=list,
        description="Alternative names referring to the same concept",
    )
    examples: list[str] = PydanticField(
        default_factory=list,
        description="Example usages, e.g. sample column or table names",
    )
    related_terms: list[str] = PydanticField(
        default_factory=list,
        description="Names of related terms in the dictionary",
    )


class BusinessDictionary(NldNamedBaseModel):
    """Namespaced business vocabulary used by agents to name tables and fields."""

    terms: dict[str, Term] = PydanticField(
        default_factory=dict,
        description="Terms indexed by canonical term name",
    )


class NamespacedBusinessDictionary(NldNamespacedBaseModelWrapper[BusinessDictionary]):
    """BusinessDictionary wrapped with namespace information."""
