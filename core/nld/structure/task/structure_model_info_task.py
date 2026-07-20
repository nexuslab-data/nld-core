from typing import TYPE_CHECKING, Any, ClassVar

from nld.parameters import ExecutionParameterDefinition
from nld.service import EntityTypeNames
from nld.task.base import StandardTask

if TYPE_CHECKING:
    from nld.structure.structure_model.structure_model_link import StructureModelLink


class StructureModelInfoTask(StandardTask):
    """Display a structure model and every link it defines.

    Two output formats are available:

    - ``diagram`` (default): a compact visual rendering of each link, drawing the
      left structure above the right one with a downward arrow carrying the
      cardinality, and the join columns shown as ``(left)`` / ``(right)`` pairs.
    - ``detailed``: the full textual dump (left/right structures, cardinality,
      optional condition, attributes and every field mapping).
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        "name",
        ExecutionParameterDefinition(name="namespace", mandatory=False),
        ExecutionParameterDefinition(name="output", mandatory=False),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        name: str,
        namespace: str | None = None,
        output: str = "diagram",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.output = output
        self.execution_context.load_entities(
            entity_types=[EntityTypeNames.STRUCTURE_MODEL]
        )
        namespaced = self.execution_context.entity_registry.get_structure_model(
            entity_key=name,
            namespace=namespace,
        )
        self.model_namespace = namespaced.namespace
        self.model = namespaced.model

    def run(self, **kwargs: Any) -> bool:
        title_lines = [f"Structure Model: {self.model.name}"]
        if self.model_namespace:
            title_lines.append(f"Namespace: {self.model_namespace}")
        if self.model.description:
            title_lines.append(f"Description: {self.model.description}")
        self.log_section_header(*title_lines)
        self.log_empty_line()

        if not self.model.links:
            self.log_info("  No links defined")
            return True

        if self.output == "detailed":
            self._render_detailed()
        else:
            self._render_diagram()
        return True

    def _render_detailed(self) -> None:
        for link_name, link in self.model.links.items():
            self.log_info(f"Link: {link_name}")
            self.log_info(f"  left_structure  : {link.left_structure}")
            self.log_info(f"  right_structure : {link.right_structure}")
            self.log_info(f"  cardinality     : {link.cardinality.value}")
            if link.condition:
                self.log_info(f"  condition       : {link.condition}")
            if link.attributes:
                self.log_info(f"  attributes      : {link.attributes}")
            self.log_info("  left_to_right_mappings (left -> right):")
            for mapping in link.left_to_right_mappings:
                self.log_info(f"    {mapping.left} -> {mapping.right}")
            self.log_empty_line()

    def _render_diagram(self) -> None:
        for link_name, link in self.model.links.items():
            self.log_info(f"Link: {link_name}")
            for line in self._diagram_lines(link):
                self.log_info(line)
            self.log_empty_line()

    @staticmethod
    def _diagram_lines(link: "StructureModelLink") -> list[str]:
        """Render a single link as a top-to-bottom left -> right diagram."""
        # Each mapping becomes a centred column so the connector lines up.
        cells_top: list[str] = []
        cells_mid: list[str] = []
        cells_bot: list[str] = []
        for mapping in link.left_to_right_mappings:
            left_text = f"({mapping.left})"
            right_text = f"({mapping.right})"
            width = max(len(left_text), len(right_text))
            cells_top.append(left_text.center(width))
            cells_mid.append("│".center(width))
            cells_bot.append(right_text.center(width))
        mappings_top = "   ".join(cells_top)
        mappings_mid = "   ".join(cells_mid)
        mappings_bot = "   ".join(cells_bot)

        gutter_top = "      │"
        gutter_mid = f"      │ {link.cardinality.value}"
        gutter_bot = "      ▼"
        pad = max(len(gutter_top), len(gutter_mid), len(gutter_bot)) + 3

        return [
            str(link.left_structure),
            f"{gutter_top:<{pad}}{mappings_top}".rstrip(),
            f"{gutter_mid:<{pad}}{mappings_mid}".rstrip(),
            f"{gutter_bot:<{pad}}{mappings_bot}".rstrip(),
            str(link.right_structure),
        ]
