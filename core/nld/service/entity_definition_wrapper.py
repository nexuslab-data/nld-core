from nld.logging import NldLoggable
from nld.pydantic import NldBaseModel

from .entity_definition import EntityDefinition


class EntityDefinitionWrapper(NldLoggable):
    """
    Wrapper for entity definitions with dependency resolution.

    Analyzes dependencies between entity definitions based on their
    model types and provides methods to order them from children to
    parents for proper loading order.
    """

    def __init__(self, entity_definitions: list[EntityDefinition]) -> None:
        """
        Initialize the wrapper with entity definitions.

        Args:
            entity_definitions: List of entity definitions to manage
        """
        super().__init__()
        self.entity_definitions = entity_definitions
        self._dependency_graph: dict[str, set[str]] = {}
        self._build_dependency_graph()

    def _build_dependency_graph(self) -> None:
        """
        Build a dependency graph from entity definitions.

        The graph maps entity names to the set of entities they depend on.
        """
        self._dependency_graph = {}

        entity_map: dict[type[NldBaseModel], str] = {
            entity_def.model_type: entity_def.name
            for entity_def in self.entity_definitions
        }

        for entity_def in self.entity_definitions:
            dependencies: set[str] = set()

            contained_types = entity_def.model_type.get_contained_model_types()

            for contained_type in contained_types:
                if contained_type in entity_map:
                    dependencies.add(entity_map[contained_type])

            self._dependency_graph[entity_def.name] = dependencies

    def get_dependencies(self, entity_name: str) -> set[str]:
        """
        Get the set of entities that the given entity depends on.

        Args:
            entity_name: Name of the entity

        Returns:
            Set of entity names that this entity depends on
        """
        return self._dependency_graph.get(entity_name, set())

    def get_sorted_entity_definitions(self) -> list[EntityDefinition]:
        """
        Get entity definitions sorted from children to parents.

        Performs a topological sort to ensure that entities are ordered
        such that dependencies come before dependents (children before parents).

        Returns:
            List of entity definitions sorted by dependency order

        Raises:
            ValueError: If circular dependencies are detected
        """
        in_degree: dict[str, int] = {}
        for entity_def in self.entity_definitions:
            in_degree[entity_def.name] = len(
                self._dependency_graph.get(entity_def.name, set())
            )

        queue: list[str] = [name for name, degree in in_degree.items() if degree == 0]

        sorted_names: list[str] = []

        while queue:
            current = queue.pop(0)
            sorted_names.append(current)

            for entity_name in self._dependency_graph:
                if current in self._dependency_graph[entity_name]:
                    in_degree[entity_name] -= 1
                    if in_degree[entity_name] == 0:
                        queue.append(entity_name)

        if len(sorted_names) != len(self.entity_definitions):
            raise ValueError("Circular dependency detected in entity definitions")

        entity_def_map: dict[str, EntityDefinition] = {
            entity_def.name: entity_def for entity_def in self.entity_definitions
        }

        return [entity_def_map[name] for name in sorted_names]

    def has_circular_dependencies(self) -> bool:
        """
        Check if there are circular dependencies in the entity definitions.

        Returns:
            True if circular dependencies exist, False otherwise
        """
        try:
            self.get_sorted_entity_definitions()
            return False
        except ValueError:
            return True

    def get_dependency_graph(self) -> dict[str, set[str]]:
        """
        Get the complete dependency graph.

        Returns:
            Dictionary mapping entity names to their dependencies
        """
        return self._dependency_graph.copy()
