from typing import Any, get_origin

from pydantic_core import CoreSchema, core_schema

from pydantic import GetCoreSchemaHandler

from .named_base_model import NldNamedBaseModel
from .namespace import NldNamespace


class NldEntityReference[T: NldNamedBaseModel](str):
    """A dot-separated reference to an entity: 'namespace.entity_name'.

    Parsing rules:
    - Last dot-separated segment is the entity name.
    - Everything before is the namespace.
    - No dot means root namespace + entity name.
    - Leading dot (e.g. ".my_entity") means root namespace.

    Examples:
        >>> NldEntityReference("source.my_table")
        'source.my_table'
        >>> ref = NldEntityReference("source.my_table")
        >>> ref.namespace
        'source'
        >>> ref.entity_name
        'my_table'
    """

    def __new__(cls, value: str | None = None) -> "NldEntityReference[T]":
        if value is None or value == "":
            raise ValueError("Entity reference must not be None or empty")

        if not isinstance(value, str):
            raise TypeError(f"Entity reference expects str, got {type(value).__name__}")

        if "/" in value or "\\" in value:
            raise ValueError(f"Entity reference must not contain slashes: '{value}'")

        if ".." in value:
            raise ValueError(
                f"Entity reference must not contain consecutive dots: '{value}'"
            )

        return str.__new__(cls, value)

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        origin = get_origin(source_type)
        actual_cls = origin if origin is not None else source_type
        return core_schema.no_info_after_validator_function(
            actual_cls,
            core_schema.str_schema(),
            serialization=core_schema.plain_serializer_function_ser_schema(str),
        )

    def _parse_reference(self) -> tuple[NldNamespace, str]:
        """Parse into (namespace, entity_name) tuple."""
        raw = str(self)

        if raw.startswith("."):
            entity_name = raw[1:]
            return NldNamespace(NldNamespace.ROOT_VALUE), entity_name

        if "." not in raw:
            return NldNamespace(NldNamespace.ROOT_VALUE), raw

        last_dot = raw.rfind(".")
        namespace_part = raw[:last_dot]
        entity_name = raw[last_dot + 1 :]
        return NldNamespace(namespace_part), entity_name

    @property
    def entity_name(self) -> str:
        """The entity name (last segment)."""
        return self._parse_reference()[1]

    @property
    def namespace(self) -> NldNamespace:
        """The namespace (everything before the last segment)."""
        return self._parse_reference()[0]

    def resolve(self, entity_type: str) -> T:
        """Resolve this reference to a deep-copied entity from the registry.

        Uses NldExecutionContext.require_current().entity_registry to look
        up the entity, then returns a deep copy.

        Args:
            entity_type: The type of entity to resolve (e.g. EntityTypeNames.STRUCTURE)

        Returns:
            A deep copy of the resolved entity
        """
        from nld.pydantic.base_model import NldBaseModel
        from nld.task.context import NldExecutionContext

        namespace, entity_name = self._parse_reference()
        wrapper = NldExecutionContext.require_current().entity_registry.get_entity(
            entity_type=entity_type,
            entity_key=entity_name,
            namespace=str(namespace),
            use_search_direction=True,
        )
        return NldBaseModel.deep_copy(wrapper.model)  # type: ignore[return-value]
