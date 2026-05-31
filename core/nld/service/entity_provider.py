import os.path
from pathlib import Path
from typing import Any, Literal

import yaml

from nld.logging import NldLoggable
from nld.pydantic import (
    NldBaseModel,
    NldNamedBaseModel,
    NldNamespace,
    NldNamespacedBaseModelWrapper,
    ResolutionContext,
    select_by_namespace_priority,
)

from .entity_definition import EntityDefinition
from .exceptions import ObjectReadNoDirectoryException


class EntityProvider(NldLoggable):
    """Entity Provider Service.

    Stores all the entities and provides standard methods to retrieve them,
    organized by type, namespace, and name.
    """

    ROOT_NAMESPACE: str = NldNamespace.ROOT_VALUE

    def __init__(self, entity_definitions: list[EntityDefinition]) -> None:
        super().__init__()
        self._entities_loaded: bool = False
        self.entity_definitions: list[EntityDefinition] = entity_definitions
        self.entities: dict[str, dict[NldNamespace, dict[str, NldBaseModel]]] = {}

    @classmethod
    def _normalize_namespace(cls, namespace: str | None) -> NldNamespace:
        """Normalize namespace to ROOT_NAMESPACE (".") for consistency."""
        return NldNamespace(namespace)

    @classmethod
    def _get_namespace_hierarchy(cls, namespace: str) -> list[NldNamespace]:
        """
        Get namespace hierarchy from root to the given namespace.

        Args:
            namespace: Namespace to get hierarchy for

        Returns:
            List of namespaces from root to child (inclusive)

        Example:
            >>> EntityProvider._get_namespace_hierarchy("ns1.ns2.ns3")
            [".", "ns1", "ns1.ns2", "ns1.ns2.ns3"]
        """
        return NldNamespace(namespace).hierarchy

    def get_entity_definition(self, entity_name: str) -> EntityDefinition | None:
        """Get the entity definition for the given entity name."""
        matching_definitions = [
            entity_def
            for entity_def in self.entity_definitions
            if entity_def.name == entity_name
        ]
        return matching_definitions[0] if len(matching_definitions) > 0 else None

    def get_entity_definitions_by_category(
        self,
        category: str,
    ) -> list[EntityDefinition]:
        """Get all entity definitions that belong to a specific category."""
        return [
            entity_def
            for entity_def in self.entity_definitions
            if entity_def.category == category
        ]

    def get_categories(self) -> list[str]:
        """Get all unique categories from entity definitions."""
        categories = set()
        for entity_def in self.entity_definitions:
            if entity_def.category is not None:
                categories.add(entity_def.category)
        return sorted(categories)

    def get_entity_definitions_grouped_by_category(
        self,
    ) -> dict[str | None, list[EntityDefinition]]:
        """
        Get entity definitions grouped by their category.

        Entities without a category are grouped under None key.
        """
        grouped: dict[str | None, list[EntityDefinition]] = {}
        for entity_def in self.entity_definitions:
            category = entity_def.category
            if category not in grouped:
                grouped[category] = []
            grouped[category].append(entity_def)
        return grouped

    def replace_entity_type_entities(
        self,
        key: str,
        entity_dict: dict[str, NldBaseModel],
        namespace: str | None = None,
    ) -> None:
        """
        Merge entities for a given type and namespace.

        Args:
            key: Entity type key
            entity_dict: Dictionary of entities to merge
            namespace: Namespace (defaults to root ".")
        """
        normalized_namespace = self._normalize_namespace(namespace=namespace)

        if key not in self.entities:
            self.entities[key] = {}

        if normalized_namespace not in self.entities[key]:
            self.entities[key][normalized_namespace] = {}

        self.entities[key][normalized_namespace].update(entity_dict)

    def get_available_entity_types(self) -> list[str]:
        """Get all the available entity types."""
        return list(self.entities.keys())

    def get_entity_type_namespaces(self, entity_type: str) -> list[str]:
        """
        Get all namespaces where entities of the given type exist.

        Args:
            entity_type: The type of entity

        Returns:
            List of namespace strings where this entity type has entities.
            Returns empty list if the entity type doesn't exist.

        Example:
            >>> provider.get_entity_type_namespaces("structure")
            [".", "level1", "level1.level2"]
        """
        if entity_type not in self.entities:
            return []

        return sorted(self.entities[entity_type].keys())

    def get_all_namespaces(self) -> list[str]:
        """
        Get all namespaces across all entity types.

        Returns:
            Sorted list of unique namespace strings where any entities exist.
            Returns empty list if no entities exist.

        Example:
            >>> provider.get_all_namespaces()
            [".", "level1", "level1.level2", "product1"]
        """
        namespaces: set[str] = set()

        for entity_type in self.entities.values():
            namespaces.update(entity_type.keys())

        return sorted(namespaces)

    def get_entity_type_namespace_hierarchy(
        self, entity_type: str, namespace: str | None = None
    ) -> dict[NldNamespace, list[NldNamespace]]:
        """
        Get the namespace child hierarchy for a given entity type.

        Returns a dictionary mapping each namespace to its direct children,
        based on the namespaces where entities of this type exist, starting
        from the specified parent namespace.

        Args:
            entity_type: The type of entity
            namespace: Reference parent namespace to use as root. If None,
                       returns full hierarchy from root. If specified, returns
                       only that namespace and its descendants.

        Returns:
            Dictionary mapping each namespace to list of direct child
            namespaces. Returns empty dict if entity type doesn't exist.
            When namespace is specified, only includes that namespace and
            its descendants.

        Example:
            >>> provider.get_entity_type_namespace_hierarchy("structure")
            {
                ".": ["level1", "product1"],
                "level1": ["level1.level2"],
                "level1.level2": [],
                "product1": []
            }
            >>> provider.get_entity_type_namespace_hierarchy("structure", "level1")
            {
                "level1": ["level1.level2"],
                "level1.level2": []
            }
        """
        if entity_type not in self.entities:
            return {}

        all_namespaces = sorted(self.entities[entity_type].keys())

        if namespace is None:
            filtered_namespaces = all_namespaces
        else:
            reference_namespace = self._normalize_namespace(namespace=namespace)
            if reference_namespace == self.ROOT_NAMESPACE:
                filtered_namespaces = all_namespaces
            else:
                filtered_namespaces = [
                    ns
                    for ns in all_namespaces
                    if ns == reference_namespace
                    or ns.startswith(reference_namespace + ".")
                ]

        hierarchy: dict[NldNamespace, list[NldNamespace]] = {}

        for ns in filtered_namespaces:
            hierarchy[ns] = []

        for ns in filtered_namespaces:
            if namespace is None:
                if ns == self.ROOT_NAMESPACE:
                    continue
            else:
                reference_namespace = self._normalize_namespace(namespace=namespace)
                if ns == reference_namespace:
                    continue

            parent = self._get_parent_namespace(namespace=ns)

            while parent not in filtered_namespaces and parent != self.ROOT_NAMESPACE:
                parent = self._get_parent_namespace(namespace=parent)

            if parent in filtered_namespaces:
                hierarchy[parent].append(ns)

        return hierarchy

    @classmethod
    def _get_parent_namespace(cls, namespace: str) -> NldNamespace:
        """
        Get the parent namespace of the given namespace.

        Args:
            namespace: Namespace to get parent for

        Returns:
            Parent namespace string. Returns ROOT_NAMESPACE for root children.

        Example:
            >>> EntityProvider._get_parent_namespace("level1.level2.level3")
            "level1.level2"
            >>> EntityProvider._get_parent_namespace("level1")
            "."
        """
        return NldNamespace(namespace).parent

    def _get_namespace_descendants(
        self, entity_type: str, namespace: str
    ) -> list[NldNamespace]:
        """
        Get all descendant namespaces for a given namespace and entity type.

        Uses the namespace hierarchy to find all children recursively.

        Args:
            entity_type: The type of entity
            namespace: The parent namespace

        Returns:
            List of namespace strings including the parent and all descendants

        Example:
            >>> provider._get_namespace_descendants("structure", "level1")
            ["level1", "level1.level2", "level1.level2.level3"]
        """
        if entity_type not in self.entities:
            return [NldNamespace(namespace)]

        hierarchy = self.get_entity_type_namespace_hierarchy(
            entity_type=entity_type, namespace=namespace
        )

        descendants = list(hierarchy.keys())
        return sorted(descendants)

    def _get_namespace_ancestors(
        self, entity_type: str, namespace: str
    ) -> list[NldNamespace]:
        """
        Get all ancestor namespaces for a given namespace and entity type.

        Returns namespaces from root to the current namespace that exist
        in the entity storage.

        Args:
            entity_type: The type of entity
            namespace: The child namespace

        Returns:
            List of namespace strings including root and all ancestors up to
            the current namespace that have entities stored

        Example:
            >>> provider._get_namespace_ancestors("org", "level1.level2")
            [".", "level1", "level1.level2"]
        """
        if entity_type not in self.entities:
            return [NldNamespace(namespace)]

        hierarchy = self._get_namespace_hierarchy(namespace=namespace)
        existing_namespaces = set(self.entities[entity_type].keys())

        ancestors = [ns for ns in hierarchy if ns in existing_namespaces]
        return ancestors

    def get_entity_dict(
        self, namespace: str | None = None, include_children: bool = True
    ) -> dict[str, dict[str, Any]]:
        """
        Get the complete entity dictionary for a given namespace.

        By default, includes entities from the namespace and all its child
        namespaces. Child namespace values override parent namespace values
        when merging.

        Args:
            namespace: Namespace to filter by (defaults to root ".")
            include_children: Include child namespaces (default True)

        Returns:
            Dictionary mapping entity type to entities from namespace and
            optionally descendants

        Example:
            >>> # root has: entity1 = {"a": 1}
            >>> # level1 has: entity1 = {"b": 2}
            >>> # level1.level2 has: entity1 = {"c": 3}
            >>> provider.get_entity_dict("level1")
            {"entity_type": {"b": 2, "c": 3}}
        """
        normalized_namespace = self._normalize_namespace(namespace=namespace)
        result: dict[str, dict[str, Any]] = {}

        if include_children:
            for entity_type in self.entities:
                descendants = self._get_namespace_descendants(
                    entity_type=entity_type, namespace=normalized_namespace
                )
                merged_entities: dict[str, Any] = {}

                for descendant_namespace in descendants:
                    if descendant_namespace in self.entities[entity_type]:
                        merged_entities.update(
                            self.entities[entity_type][descendant_namespace]
                        )

                if merged_entities:
                    result[entity_type] = merged_entities
        else:
            for entity_type in self.entities:
                if normalized_namespace in self.entities[entity_type]:
                    result[entity_type] = dict(
                        self.entities[entity_type][normalized_namespace]
                    )

        return result

    def get_entity_dict_for_resolution(
        self,
        namespace: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """
        Build entity dictionary for resolution context, respecting search_direction.

        For each entity type, checks the entity definition's search_direction:
        - "parents": includes entities from ancestor namespaces (root to current),
          with deeper namespaces overriding shallower ones.
        - "children" (default): includes entities from descendant namespaces,
          same as get_entity_dict behavior.

        Entity types without a definition fall back to children behavior.

        Args:
            namespace: Namespace to build resolution context for (defaults to root)

        Returns:
            Dictionary mapping entity type to merged entities dict

        Example:
            >>> # field_adapter (search_direction="parents") defined at root
            >>> # structure (search_direction="children") defined at ns1
            >>> provider.get_entity_dict_for_resolution(namespace="ns1")
            {"field_adapter": {...from root...}, "structure": {...from ns1+children...}}
        """
        normalized_namespace = self._normalize_namespace(namespace=namespace)
        result: dict[str, dict[str, Any]] = {}

        for entity_type in self.entities:
            entity_definition = self.get_entity_definition(
                entity_name=entity_type,
            )
            search_parents = (
                entity_definition is not None
                and entity_definition.search_direction == "parents"
            )

            if search_parents:
                namespaces_to_search = self._get_namespace_ancestors(
                    entity_type=entity_type,
                    namespace=normalized_namespace,
                )
            else:
                namespaces_to_search = self._get_namespace_descendants(
                    entity_type=entity_type,
                    namespace=normalized_namespace,
                )

            merged_entities: dict[str, Any] = {}
            for ns in namespaces_to_search:
                if ns in self.entities[entity_type]:
                    merged_entities.update(self.entities[entity_type][ns])

            if merged_entities:
                result[entity_type] = merged_entities

        return result

    def get_all_entity_dict(self) -> dict[str, dict[NldNamespace, dict[str, Any]]]:
        """
        Get the complete entity dictionary across all namespaces.

        Returns:
            Full nested dictionary: entity_type -> namespace -> entity_name -> entity
        """
        return self.entities

    def _get_all_entities_with_namespaces(
        self,
        entity_type: str,
        namespace: str | None = None,
        include_children: bool = True,
        use_search_direction: bool = False,
    ) -> dict[str, list[NldNamespacedBaseModelWrapper[Any]]]:
        """
        Get all entities grouped by key with their namespace information.

        Returns a dictionary where each key maps to a list of wrappers from
        different namespaces where that entity exists.

        Args:
            entity_type: The type of entity to retrieve
            namespace: Namespace (defaults to root ".")
            include_children: Include child namespaces (default True). This
                parameter is ignored when use_search_direction is True.
            use_search_direction: If True, uses the entity definition's
                search_direction to determine whether to search children
                or parents. If False, uses the include_children parameter.

        Returns:
            Dictionary mapping entity names to list of NldNamespacedBaseModelWrapper
            instances from different namespaces
        """
        normalized_namespace = self._normalize_namespace(namespace=namespace)

        if entity_type not in self.entities:
            return {}

        result: dict[str, list[NldNamespacedBaseModelWrapper[Any]]] = {}

        if use_search_direction:
            entity_definition = self.get_entity_definition(entity_name=entity_type)
            search_parents = (
                entity_definition is not None
                and entity_definition.search_direction == "parents"
            )

            if search_parents:
                namespaces_to_search = self._get_namespace_ancestors(
                    entity_type=entity_type,
                    namespace=normalized_namespace,
                )
            else:
                namespaces_to_search = self._get_namespace_descendants(
                    entity_type=entity_type,
                    namespace=normalized_namespace,
                )

            for ns in namespaces_to_search:
                if ns in self.entities[entity_type]:
                    for key, model in self.entities[entity_type][ns].items():
                        if key not in result:
                            result[key] = []
                        result[key].append(
                            NldNamespacedBaseModelWrapper(
                                model=model,
                                namespace=ns,
                            )
                        )
        elif include_children:
            descendants = self._get_namespace_descendants(
                entity_type=entity_type,
                namespace=normalized_namespace,
            )

            for descendant_namespace in descendants:
                if descendant_namespace in self.entities[entity_type]:
                    for key, model in self.entities[entity_type][
                        descendant_namespace
                    ].items():
                        if key not in result:
                            result[key] = []
                        result[key].append(
                            NldNamespacedBaseModelWrapper(
                                model=model,
                                namespace=descendant_namespace,
                            )
                        )
        else:
            if normalized_namespace in self.entities[entity_type]:
                for key, model in self.entities[entity_type][
                    normalized_namespace
                ].items():
                    result[key] = [
                        NldNamespacedBaseModelWrapper(
                            model=model,
                            namespace=normalized_namespace,
                        )
                    ]

        return result

    def get_entity_keys(
        self,
        entity_type: str,
        namespace: str | None = None,
        include_children: bool = True,
        use_search_direction: bool = False,
    ) -> list[str]:
        """
        Get the list of entity keys for the entity type and namespace.

        Args:
            entity_type: The type of entity
            namespace: Namespace (defaults to root ".")
            include_children: Include child namespaces (default True). Ignored
                when use_search_direction is True.
            use_search_direction: If True, uses the entity definition's
                search_direction to determine search behavior.

        Returns:
            List of entity names in that namespace and related namespaces
        """
        all_entities = self._get_all_entities_with_namespaces(
            entity_type=entity_type,
            namespace=namespace,
            include_children=include_children,
            use_search_direction=use_search_direction,
        )
        return list(all_entities.keys())

    def list_entity_keys(
        self,
        entity_type: str,
        namespace: str | None = None,
    ) -> list[str]:
        """
        List all entity keys for the entity type across all namespaces.

        This method always includes all child namespaces and ignores the
        entity definition's search_direction. Use this for inventory or
        reporting purposes where you need the complete list of all entities.

        Args:
            entity_type: The type of entity
            namespace: Starting namespace (defaults to root ".")

        Returns:
            List of all entity keys in the namespace and all descendants
        """
        return self.get_entity_keys(
            entity_type=entity_type,
            namespace=namespace,
            include_children=True,
            use_search_direction=False,
        )

    def get_entity(
        self,
        entity_type: str,
        entity_key: str,
        namespace: str | None = None,
        include_children: bool = True,
        use_search_direction: bool = False,
    ) -> NldNamespacedBaseModelWrapper[Any]:
        """
        Get the entity of type entity_type and name entity_key.

        When multiple entities exist with the same key across namespaces,
        the priority depends on the search direction:
        - For children search: returns entity closest to root
        - For parents search: returns entity closest to current namespace

        Args:
            entity_type: The type of entity
            entity_key: The name/key of the entity
            namespace: Namespace (defaults to root ".")
            include_children: Include child namespaces (default True). Ignored
                when use_search_direction is True.
            use_search_direction: If True, uses the entity definition's
                search_direction to determine search behavior and priority.

        Returns:
            NldNamespacedBaseModelWrapper containing the entity and its actual
            namespace (where it's stored in the registry)

        Raises:
            ValueError: If entity_type is not found
            RuntimeError: If entity_key is not found in the namespace
        """
        if entity_type not in self.entities.keys():
            raise ValueError(f"No Entity Type stored with name: {entity_type}")

        normalized_namespace = self._normalize_namespace(namespace=namespace)

        all_entities = self._get_all_entities_with_namespaces(
            entity_type=entity_type,
            namespace=namespace,
            include_children=include_children,
            use_search_direction=use_search_direction,
        )

        if entity_key not in all_entities:
            entity_definition = self.get_entity_definition(
                entity_name=entity_type,
            )
            entity_label = (
                entity_definition.display_name
                if entity_definition is not None
                and entity_definition.display_name is not None
                else entity_type
            )
            raise RuntimeError(
                f"No {entity_label} with key {entity_key} "
                f"for namespace {normalized_namespace} is available."
            )

        entity_wrappers = all_entities[entity_key]

        priority: Literal["root", "deepest"] = "root"
        if use_search_direction:
            entity_definition = self.get_entity_definition(entity_name=entity_type)
            if (
                entity_definition is not None
                and entity_definition.search_direction == "parents"
            ):
                priority = "deepest"

        return select_by_namespace_priority(
            entities=entity_wrappers,
            priority=priority,
        )

    def get_entities(
        self,
        entity_type: str,
        entity_keys: list[str] | None = None,
        namespace: str | None = None,
        include_children: bool = True,
        use_search_direction: bool = False,
    ) -> list[NldNamespacedBaseModelWrapper[Any]]:
        """
        Get the list of entities of type entity_type.

        When entity_keys is None, returns all entities for the entity type.
        When multiple entities exist with the same key across namespaces,
        the priority depends on the search direction:
        - For children search: returns entity closest to root
        - For parents search: returns entity closest to current namespace

        Args:
            entity_type: The type of entity
            entity_keys: List of entity names to retrieve, or None for all
            namespace: Namespace (defaults to root ".")
            include_children: Include child namespaces (default True). Ignored
                when use_search_direction is True.
            use_search_direction: If True, uses the entity definition's
                search_direction to determine search behavior and priority.

        Returns:
            List of NldNamespacedBaseModelWrapper instances

        Raises:
            ValueError: If entity_type is not found
        """
        if entity_type not in self.entities:
            raise ValueError(f"No Entity Type stored with name: {entity_type}")

        all_entities = self._get_all_entities_with_namespaces(
            entity_type=entity_type,
            namespace=namespace,
            include_children=include_children,
            use_search_direction=use_search_direction,
        )

        keys_to_retrieve = (
            entity_keys if entity_keys is not None else list(all_entities.keys())
        )

        priority: Literal["root", "deepest"] = "root"
        if use_search_direction:
            entity_definition = self.get_entity_definition(entity_name=entity_type)
            if (
                entity_definition is not None
                and entity_definition.search_direction == "parents"
            ):
                priority = "deepest"

        result: list[NldNamespacedBaseModelWrapper[Any]] = []
        for key in keys_to_retrieve:
            if key in all_entities:
                selected = select_by_namespace_priority(
                    entities=all_entities[key],
                    priority=priority,
                )
                result.append(selected)

        return result

    def get_entities_as_dict(
        self,
        entity_type: str,
        entity_keys: list[str] | None = None,
        namespace: str | None = None,
        include_children: bool = True,
        use_search_direction: bool = False,
    ) -> dict[str, NldNamespacedBaseModelWrapper[Any]]:
        """
        Get the entities as a dictionary for the entity type and keys provided.

        When entity_keys is None, returns all entities for the entity type.
        When multiple entities exist with the same key across namespaces,
        the priority depends on the search direction:
        - For children search: returns entity closest to root
        - For parents search: returns entity closest to current namespace

        Args:
            entity_type: The type of entity
            entity_keys: List of entity names to retrieve, or None for all
            namespace: Namespace (defaults to root ".")
            include_children: Include child namespaces (default True). Ignored
                when use_search_direction is True.
            use_search_direction: If True, uses the entity definition's
                search_direction to determine search behavior and priority.

        Returns:
            Dictionary mapping entity names to NldNamespacedBaseModelWrapper instances

        Raises:
            ValueError: If entity_type is not found
        """
        if entity_type not in self.entities:
            raise ValueError(f"No Entity Type stored with name: {entity_type}")

        all_entities = self._get_all_entities_with_namespaces(
            entity_type=entity_type,
            namespace=namespace,
            include_children=include_children,
            use_search_direction=use_search_direction,
        )

        keys_to_retrieve = (
            entity_keys if entity_keys is not None else list(all_entities.keys())
        )

        priority: Literal["root", "deepest"] = "root"
        if use_search_direction:
            entity_definition = self.get_entity_definition(entity_name=entity_type)
            if (
                entity_definition is not None
                and entity_definition.search_direction == "parents"
            ):
                priority = "deepest"

        result: dict[str, NldNamespacedBaseModelWrapper[Any]] = {}
        for key in keys_to_retrieve:
            if key in all_entities:
                result[key] = select_by_namespace_priority(
                    entities=all_entities[key],
                    priority=priority,
                )

        return result

    def get_entities_on_namespace(
        self,
        namespace: str | None = None,
    ) -> dict[str, dict[str, NldNamespacedBaseModelWrapper[Any]]]:
        """
        Get all entities for a namespace, respecting each type's search direction.

        Returns a dictionary where each entity type maps to its entities dict.
        Each entity type uses its configured search_direction to determine
        which namespaces to search (children or parents).

        Args:
            namespace: Namespace to get entities for (defaults to root ".")

        Returns:
            Dictionary mapping entity type names to dictionaries of
            entity key -> NldNamespacedBaseModelWrapper

        Example:
            >>> result = provider.get_entities_on_namespace(namespace="ns1")
            >>> result["org"]  # Entities from parents (root -> ns1)
            >>> result["structure"]  # Entities from children (ns1 -> descendants)
        """
        result: dict[str, dict[str, NldNamespacedBaseModelWrapper[Any]]] = {}

        for entity_definition in self.entity_definitions:
            entity_type = entity_definition.name

            if entity_type not in self.entities:
                result[entity_type] = {}
                continue

            result[entity_type] = self.get_entities_as_dict(
                entity_type=entity_type,
                namespace=namespace,
                use_search_direction=True,
            )

        return result

    def load_entities(
        self,
        root_directory: str,
        fail_on_missing_folder: bool = False,
        force_reload: bool = False,
    ) -> None:
        """
        Load all entities from the root directory.

        Recursively loads entities from each entity type's folder and subdirectories.
        Subdirectories automatically become namespaces based on their relative paths.

        Args:
            root_directory: Base directory containing entity folders
            fail_on_missing_folder: Raise exception if folder doesn't exist
            force_reload: Force reload even if entities were already loaded

        Example:
            Given structure:
                root/
                    flows/
                        flow1.yml               -> namespace "."
                        source/product1/
                            flow2.yml           -> namespace "source/product1"
                    config/org/
                        org1.yml                -> namespace "."

            Loads flow1 and org1 into namespace ".",
            and flow2 into namespace "source/product1"
        """
        if self._entities_loaded and not force_reload:
            return

        for entity_definition in self.entity_definitions:
            self.load_from_entity_definition(
                root_directory=root_directory,
                entity_definition=entity_definition,
                fail_on_missing_folder=fail_on_missing_folder,
            )

        self._entities_loaded = True

    def load_from_entity_definition(
        self,
        root_directory: str,
        entity_definition: EntityDefinition,
        fail_on_missing_folder: bool,
    ) -> None:
        """
        Load entities from a specific entity definition.

        Recursively loads entities from the entity folder and all subdirectories.
        Each subdirectory becomes a namespace based on its relative path.

        Args:
            root_directory: Base directory containing entity folders
            entity_definition: Definition of the entity type to load
            fail_on_missing_folder: Raise exception if folder doesn't exist

        Example:
            Given structure:
                root/flows/
                    flow1.yml           -> namespace "."
                    source/product1/
                        flow2.yml       -> namespace "source/product1"

            Loads flow1 into namespace "." and flow2 into namespace "source/product1"
        """
        from nld.service.model_read_util import (
            read_entities_from_yaml_file_list,
            read_files_from_file_list,
        )
        from nld.utils.file_util import (
            get_files_grouped_by_subdirectory,
        )
        from nld.utils.jinja_utils import JINJA2_FILE_STANDARD_REGEX
        from nld.utils.yaml_util import YAML_FILE_STANDARD_REGEX

        entity_folder_path = os.path.join(root_directory, entity_definition.folder_name)

        if not os.path.exists(entity_folder_path):
            if fail_on_missing_folder:
                raise ObjectReadNoDirectoryException(
                    folder_path=entity_folder_path,
                    data_class=entity_definition.model_type,
                )
            else:
                self.replace_entity_type_entities(
                    key=entity_definition.name,
                    entity_dict={},
                    namespace=".",
                )
                return

        pattern = (
            YAML_FILE_STANDARD_REGEX
            if entity_definition.file_format == "yaml"
            else JINJA2_FILE_STANDARD_REGEX
        )

        files_by_namespace = get_files_grouped_by_subdirectory(
            root_path=entity_folder_path,
            pattern=pattern,
        )

        for namespace, file_paths in files_by_namespace.items():
            entity_dict_for_resolution = self.get_entity_dict_for_resolution(
                namespace=namespace,
            )

            with ResolutionContext.with_registry(obj_dict=entity_dict_for_resolution):
                if entity_definition.file_format == "yaml":
                    loaded: dict[str, Any] = read_entities_from_yaml_file_list(
                        base_model_type=entity_definition.model_type,
                        file_paths=file_paths,
                    )
                else:
                    loaded = read_files_from_file_list(
                        data_class=entity_definition.model_type,
                        file_paths=file_paths,
                    )

                self.replace_entity_type_entities(
                    key=entity_definition.name,
                    entity_dict=loaded,
                    namespace=namespace,
                )

    def write_entity(
        self,
        wrapper: NldNamespacedBaseModelWrapper[Any],
        entity_type: str,
        root_directory: str,
        exclude_none: bool = False,
        sort_keys: bool = False,
    ) -> Path:
        """
        Write NldNamespacedBaseModelWrapper to a file.

        Currently only supports YAML format. Uses the model's name attribute
        as the filename (for NldNamedBaseModel instances). The name attribute
        is excluded from the output file.

        Args:
            wrapper: The namespaced model wrapper to write
            entity_type: The entity type name
            root_directory: Base directory where entities are stored
            exclude_none: Whether to exclude fields with None values
            sort_keys: Whether to sort keys alphabetically

        Returns:
            Path to the written file

        Raises:
            ValueError: If entity_type not found or file_format is not yaml
            ValueError: If model is not a NldNamedBaseModel (needs name attribute)
            ObjectReadNoDirectoryException: If target directory doesn't exist

        Example:
            >>> provider = EntityProvider(entity_definitions=[...])
            >>> wrapper = NldNamespacedBaseModelWrapper(
            ...     model=my_org,
            ...     namespace="."
            ... )
            >>> provider.write_entity(
            ...     wrapper=wrapper,
            ...     entity_type="org",
            ...     root_directory="/path/to/root"
            ... )
        """
        entity_definition = self.get_entity_definition(entity_type)
        if entity_definition is None:
            raise ValueError(f"Entity type '{entity_type}' not found")

        if entity_definition.file_format != "yaml":
            raise ValueError(
                f"Only YAML format is supported for writing. "
                f"Entity type '{entity_type}' uses format: "
                f"{entity_definition.file_format}"
            )

        if not isinstance(wrapper.model, NldNamedBaseModel):
            raise ValueError(
                f"Model must be an instance of NldNamedBaseModel to write to file. "
                f"Got: {type(wrapper.model).__name__}"
            )

        target_dir = Path(root_directory) / entity_definition.folder_name
        namespace_path = NldNamespace(wrapper.namespace).to_path(separator="/")
        if namespace_path:
            target_dir = target_dir / namespace_path

        if not target_dir.exists():
            raise ObjectReadNoDirectoryException(
                folder_path=str(target_dir),
                data_class=entity_definition.model_type,
            )

        file_name = f"{wrapper.model.name}.yaml"
        file_path = target_dir / file_name

        model_data = wrapper.model.model_dump(
            mode="python",
            exclude_none=exclude_none,
            exclude={"name"},
        )

        with file_path.open(mode="w", encoding="utf-8") as f:
            yaml.dump(
                data=model_data,
                stream=f,
                default_flow_style=False,
                sort_keys=sort_keys,
                allow_unicode=True,
            )

        return file_path
