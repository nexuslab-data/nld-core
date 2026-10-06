from typing import Any, ClassVar

from nld.parameters import ExecutionParameterDefinition
from nld.service import EntityTypeNames
from nld.task.base import StandardTask


class StructureListTask(StandardTask):
    """List structures, optionally filtered by property and/or tag.

    ``--property key=value`` (repeatable) keeps structures whose merged
    properties (``get_all_properties``, including template-contributed ones)
    match every given pair. ``--tag`` (repeatable) keeps structures carrying
    every given tag. Filters combine with AND.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(name="namespace", mandatory=False),
        ExecutionParameterDefinition(name="property", mandatory=False),
        ExecutionParameterDefinition(name="tag", mandatory=False),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        namespace: str | None = None,
        property: tuple[str, ...] = (),  # noqa: A002 (CLI param name)
        tag: tuple[str, ...] = (),
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.namespace = namespace
        self.tag_filters = list(tag or ())
        self.property_filters: dict[str, str] = {}
        for item in property or ():
            if "=" not in item:
                raise ValueError(
                    f"Invalid --property '{item}': expected key=value",
                )
            key, value = item.split("=", 1)
            self.property_filters[key.strip()] = value.strip()
        self.execution_context.load_entities(
            entity_types=[EntityTypeNames.STRUCTURE],
            namespace=self.namespace,
        )

    def _matches(self, structure: Any) -> bool:
        properties = structure.get_all_properties()
        for key, value in self.property_filters.items():
            if properties.get(key) != value:
                return False
        if self.tag_filters:
            tags = structure.get_all_tags()
            if any(t not in tags for t in self.tag_filters):
                return False
        return True

    def run(self, **kwargs: Any) -> bool:
        registry = self.execution_context.entity_registry
        structures = registry.get_structure_dict(namespace=self.namespace)

        self.log_info("Structures:")
        self.log_separator_line()

        property_keys = list(self.property_filters)
        headers = ["Name", "Namespace", "Type", *property_keys, "Tags"]
        rows: list[tuple[str, ...]] = []
        # Same-name structures from several namespaces are listed side by
        # side, so the plain name is shown next to its namespace column.
        for namespaced in sorted(
            structures.values(),
            key=lambda item: (item.model.name, str(item.namespace)),
        ):
            structure = namespaced.model
            if not self._matches(structure):
                continue
            properties = structure.get_all_properties()
            row = [
                structure.name,
                str(namespaced.namespace),
                str(structure.structure_type),
                *[str(properties.get(pk, "")) for pk in property_keys],
                ", ".join(structure.get_all_tags()),
            ]
            rows.append(tuple(row))

        if not rows:
            self.log_info("  No structures match")
            self.log_separator_line()
            return True

        self.log_aligned_table(
            headers=headers,
            rows=[list(row) for row in rows],
        )
        self.log_info(f"({len(rows)} structure(s))")
        self.log_separator_line()
        return True
