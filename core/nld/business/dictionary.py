from typing import Any, ClassVar

from pydantic import Field as PydanticField
from pydantic import field_validator, model_validator

from nld.pydantic import NldBaseModel, NldNamedBaseModel, NldNamespacedBaseModelWrapper


class Example(NldBaseModel):
    """A concrete usage of a term, optionally with a description.

    Accepts a shorthand string when there is no description (e.g.
    ``ds_legal_name``), or an explicit ``{value, description}`` mapping (e.g.
    ``{value: gender_parity, description: Workforce gender split ...}``).
    """

    value: str = PydanticField(
        description="The example usage, e.g. a sample column/table name or a "
        "composed term such as gender_parity",
    )
    description: str | None = PydanticField(
        default=None,
        description="What this particular usage means",
    )

    @model_validator(mode="before")
    @classmethod
    def _expand_shorthand(cls, data: Any) -> Any:
        """Expand a bare string into a value-only example."""
        if isinstance(data, str):
            return {"value": data}
        return data


class TermTranslation(NldBaseModel):
    """A term rendered in another language."""

    language: str = PydanticField(
        description="ISO 639 language code of this translation, e.g. 'fr'",
    )
    name: str = PydanticField(description="Term name in this language (singular)")
    plural: str | None = PydanticField(
        default=None,
        description="Plural form of the name in this language",
    )
    description: str | None = PydanticField(
        default=None,
        description="Business meaning in this language",
    )
    synonyms: list[str] = PydanticField(
        default_factory=list,
        description="Alternative names in this language",
    )
    examples: list[Example] = PydanticField(
        default_factory=list,
        description="Example usages in this language (column names, etc.)",
    )


class Term(NldBaseModel):
    """A single business term with synonyms, examples, and cross-references.

    The term is expressed in its dictionary's primary language; alternate
    languages are provided via ``translations``.
    """

    ALLOWED_GRAMMATICAL_CLASSES: ClassVar[frozenset[str]] = frozenset(
        {"noun", "adjective", "verb", "pronoun", "adverb", "preposition"}
    )

    name: str = PydanticField(description="Canonical term name (singular)")
    plural: str | None = PydanticField(
        default=None,
        description="Plural form of the term name, e.g. 'employees' for 'employee'",
    )
    grammatical_class: str | None = PydanticField(
        default=None,
        description="Grammatical class of the term; one of 'noun', 'adjective', "
        "'verb', 'pronoun', 'adverb', 'preposition'",
    )
    preferred_term: str | None = PydanticField(
        default=None,
        description="Name of another term that should be preferred over this one "
        "(e.g. legal_entity -> company)",
    )
    description: str = PydanticField(
        description="Detailed description of the business meaning",
    )
    synonyms: list[str] = PydanticField(
        default_factory=list,
        description="Alternative names referring to the same concept",
    )
    examples: list[Example] = PydanticField(
        default_factory=list,
        description="Example usages; each a bare string or a {value, description}",
    )
    related_terms: list[str] = PydanticField(
        default_factory=list,
        description="Names of related terms in the dictionary",
    )
    translations: list[TermTranslation] = PydanticField(
        default_factory=list,
        description="The term rendered in other languages",
    )

    @field_validator("grammatical_class", mode="before")
    @classmethod
    def _validate_grammatical_class(cls, value: Any) -> str | None:
        """Allow an empty value or one of the recognised grammatical classes."""
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if value not in cls.ALLOWED_GRAMMATICAL_CLASSES:
            allowed = ", ".join(sorted(cls.ALLOWED_GRAMMATICAL_CLASSES))
            raise ValueError(
                f"grammatical_class must be one of [{allowed}] or empty, got '{value}'"
            )
        return str(value)


class BusinessDictionary(NldNamedBaseModel):
    """Namespaced business vocabulary used by agents to name tables and fields."""

    language: str = PydanticField(
        default="en",
        description="Primary ISO 639 language code of this dictionary's terms, "
        "e.g. 'en'",
    )
    terms: dict[str, Term] = PydanticField(
        default_factory=dict,
        description="Terms indexed by canonical term name",
    )


class NamespacedBusinessDictionary(NldNamespacedBaseModelWrapper[BusinessDictionary]):
    """BusinessDictionary wrapped with namespace information."""
