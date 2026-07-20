from typing import Any, ClassVar

from nld.business.lookup import _get_dictionaries_in_hierarchy
from nld.parameters import ExecutionParameterDefinition
from nld.service import EntityTypeNames
from nld.task.base import StandardTask


class BusinessDictionaryListTask(StandardTask):
    """List the business-dictionary terms visible from a namespace.

    Walks the namespace hierarchy (deepest first) and lists the resolved set of
    terms — the nearest definition of each term name wins. Shows each term's
    source namespace, its languages (primary + translations) and synonyms.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(name="namespace", mandatory=False),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        namespace: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.namespace = namespace
        self.execution_context.load_entities(
            entity_types=[EntityTypeNames.BUSINESS_DICTIONARY]
        )

    def run(self, **kwargs: Any) -> bool:
        registry = self.execution_context.entity_registry
        pairs = _get_dictionaries_in_hierarchy(
            registry=registry,
            namespace=self.namespace,
        )

        self.log_info("Business dictionary terms:")
        self.log_separator_line()

        seen: set[str] = set()
        rows: list[tuple[str, ...]] = []
        for source_namespace, dictionary in pairs:
            for term_name, term in dictionary.terms.items():
                if term_name in seen:
                    continue
                seen.add(term_name)
                languages = ", ".join(
                    [dictionary.language, *(tr.language for tr in term.translations)]
                )
                rows.append(
                    (
                        term_name,
                        term.description,
                        str(source_namespace),
                        languages,
                        ", ".join(term.synonyms),
                    )
                )

        if not rows:
            self.log_info("  No terms found")
            self.log_separator_line()
            return True

        rows.sort()
        self.log_aligned_table(
            headers=["Term", "Description", "Namespace", "Languages", "Synonyms"],
            rows=[list(row) for row in rows],
            length_limitation={"Description": 50},
        )
        self.log_info(f"({len(rows)} term(s))")
        self.log_separator_line()
        return True
