from typing import TYPE_CHECKING, Literal

from nld.pydantic import NldBaseModel, NldNamespace

from .dictionary import BusinessDictionary, Term

if TYPE_CHECKING:
    from nld.service.nld_entity_registry import NldEntityRegistry


BUSINESS_DICTIONARY_ENTITY_TYPE = "business_dictionary"

MatchedOn = Literal["name", "synonym", "related_term"]


class FindMatch(NldBaseModel):
    """A single term match produced by `find_terms`."""

    term: Term
    matched_on: MatchedOn
    source_namespace: str


def _get_dictionaries_in_hierarchy(
    registry: "NldEntityRegistry",
    namespace: str | None,
) -> list[tuple[NldNamespace, BusinessDictionary]]:
    """Return `(namespace, dictionary)` pairs along the namespace hierarchy.

    Ordered from deepest (closest to the given namespace) to root so that
    namespace overrides are consumed before the general dictionary.
    """
    target = NldNamespace(namespace) if namespace is not None else NldNamespace(".")

    if BUSINESS_DICTIONARY_ENTITY_TYPE not in registry.entities:
        return []

    storage = registry.entities[BUSINESS_DICTIONARY_ENTITY_TYPE]

    pairs: list[tuple[NldNamespace, BusinessDictionary]] = []
    for level_namespace in target.hierarchy:
        namespace_entries = storage.get(level_namespace, {})
        for model in namespace_entries.values():
            if isinstance(model, BusinessDictionary):
                pairs.append((level_namespace, model))

    pairs.sort(key=lambda item: item[0].depth, reverse=True)
    return pairs


def resolve_term(
    registry: "NldEntityRegistry",
    term_name: str,
    namespace: str | None = None,
) -> Term | None:
    """Resolve a term by name, walking the namespace hierarchy upward.

    The closest namespace definition wins; the root dictionary acts as the
    general fallback.
    """
    for _, dictionary in _get_dictionaries_in_hierarchy(
        registry=registry,
        namespace=namespace,
    ):
        term = dictionary.terms.get(term_name)
        if term is not None:
            return term
    return None


def find_by_synonym(
    registry: "NldEntityRegistry",
    synonym: str,
    namespace: str | None = None,
) -> Term | None:
    """Find a term by matching its canonical name or synonyms.

    Matching also covers translations (each translation's name and synonyms), so
    a term can be resolved from any of its languages. Walks the namespace
    hierarchy from the given namespace up to root and returns the first match
    found, so namespace overrides win over general.
    """
    normalized = synonym.lower()
    for _, dictionary in _get_dictionaries_in_hierarchy(
        registry=registry,
        namespace=namespace,
    ):
        for term in dictionary.terms.values():
            if _matches_name(term, normalized) or _matches_synonym(term, normalized):
                return term
    return None


def _matches_name(term: Term, normalized: str) -> bool:
    """Whether the query matches the term's name or plural, in any language."""
    if term.name.lower() == normalized:
        return True
    if term.plural is not None and term.plural.lower() == normalized:
        return True
    for tr in term.translations:
        if tr.name.lower() == normalized:
            return True
        if tr.plural is not None and tr.plural.lower() == normalized:
            return True
    return False


def _matches_synonym(term: Term, normalized: str) -> bool:
    """Whether the query matches a synonym of the term in any language."""
    if any(candidate.lower() == normalized for candidate in term.synonyms):
        return True
    return any(
        candidate.lower() == normalized
        for tr in term.translations
        for candidate in tr.synonyms
    )


def find_terms(
    registry: "NldEntityRegistry",
    query: str,
    match_name: bool = True,
    match_synonym: bool = False,
    match_related: bool = False,
    namespace: str | None = None,
) -> list[FindMatch]:
    """Search dictionaries in the hierarchy and return every term matching `query`.

    The scope flags control which Term fields participate in the match:
    canonical `name`, `synonyms`, and/or `related_terms`. Matching is a
    case-insensitive exact string equality against each enabled field, and
    covers translations too (translation names count as `name`, translation
    synonyms as `synonym`).

    When the same term name appears in multiple namespaces the deepest
    (most specific) definition wins, preserving the `parents` override
    semantics used by `resolve_term` and `find_by_synonym`.
    """
    normalized = query.lower()
    seen_names: set[str] = set()
    results: list[FindMatch] = []

    for source_namespace, dictionary in _get_dictionaries_in_hierarchy(
        registry=registry,
        namespace=namespace,
    ):
        for term in dictionary.terms.values():
            if term.name in seen_names:
                continue

            matched_on: MatchedOn | None = None
            if match_name and _matches_name(term, normalized):
                matched_on = "name"
            elif match_synonym and _matches_synonym(term, normalized):
                matched_on = "synonym"
            elif match_related and any(
                candidate.lower() == normalized for candidate in term.related_terms
            ):
                matched_on = "related_term"

            if matched_on is not None:
                results.append(
                    FindMatch(
                        term=term,
                        matched_on=matched_on,
                        source_namespace=str(source_namespace),
                    ),
                )
                seen_names.add(term.name)

    return results
