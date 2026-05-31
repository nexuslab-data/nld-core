import threading
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, Self

import yaml

from .base_model import NldBaseModel


class ResolutionContext:
    """
    Thread-safe context manager for object reference resolution.

    This class provides a context manager that stores a registry of pre-loaded
    objects which can be referenced by name during model deserialization.

    Example:
        >>> obj_dict = {"field_adapter": {"adapter1": adapter_instance}}
        >>> with ResolutionContext.with_registry(obj_dict):
        ...     model = StructureAdapter.from_yaml(yaml_content)
    """

    _context = threading.local()

    @classmethod
    @contextmanager
    def with_registry(
        cls, obj_dict: dict[str, dict[str, Any]]
    ) -> Generator[None, None, None]:
        """
        Context manager that sets up the resolution registry.

        Args:
            obj_dict: Dictionary mapping object types to their instances
                     Format: {"object_type": {"object_name": instance}}

        Yields:
            None

        Example:
            >>> with ResolutionContext.with_registry(obj_dict):
            ...     # All from_dict/from_yaml calls will use this registry
            ...     adapter = FieldAdapter.from_yaml(yaml_content)
        """
        old_registry = getattr(cls._context, "registry", None)
        old_errors = getattr(cls._context, "errors", None)

        cls._context.registry = obj_dict
        cls._context.errors = []

        try:
            yield
        finally:
            cls._context.registry = old_registry
            cls._context.errors = old_errors

    @classmethod
    def get_registry(cls) -> dict[str, dict[str, Any]] | None:
        """
        Get the current resolution registry.

        Returns:
            Current registry dictionary, or None if no context is active
        """
        return getattr(cls._context, "registry", None)

    @classmethod
    def collect_error(cls, error_message: str) -> None:
        """
        Collect a resolution error without raising immediately.

        Args:
            error_message: Error message describing the resolution failure
        """
        errors = getattr(cls._context, "errors", None)
        if errors is not None:
            errors.append(error_message)

    @classmethod
    def get_errors(cls) -> list[str]:
        """
        Get all collected resolution errors.

        Returns:
            List of error messages
        """
        errors: list[str] | None = getattr(cls._context, "errors", None)
        return errors if errors is not None else []

    @classmethod
    def has_errors(cls) -> bool:
        """
        Check if any resolution errors have been collected.

        Returns:
            True if errors exist, False otherwise
        """
        errors = getattr(cls._context, "errors", None)
        if errors is None:
            return False
        return len(errors) > 0

    @classmethod
    def get_object(
        cls,
        object_type: str,
        object_name: str,
        field_name: str | None = None,
    ) -> Any | None:
        """
        Retrieve an object from the registry.

        Args:
            object_type: Type of object (e.g., "field_adapter")
            object_name: Name of the specific object instance
            field_name: Optional field name for error reporting

        Returns:
            The resolved object instance, or None if not found
        """
        registry = cls.get_registry()

        if registry is None:
            error_msg = (
                "No resolution context available. "
                "Wrap loading code with ResolutionContext.with_registry()"
            )
            if field_name:
                error_msg = f"Field '{field_name}': {error_msg}"
            cls.collect_error(error_msg)
            return None

        if object_type not in registry:
            return None

        if object_name not in registry[object_type]:
            available = list(registry[object_type].keys())
            error_msg = (
                f"Object '{object_name}' not found in '{object_type}'. "
                f"Available: {available[:5]}"
                + (f" (and {len(available) - 5} more)" if len(available) > 5 else "")
            )
            if field_name:
                error_msg = f"Field '{field_name}': {error_msg}"
            cls.collect_error(error_msg)
            return None

        return registry[object_type][object_name]


class NldNamedBaseModel(NldBaseModel):
    """
    Extended Pydantic BaseModel with name field and reference resolution.

    This model combines Pydantic validation with:
    - Required name field for identification
    - Logging capabilities via NldLogger (inherited from NldBaseModel)
    - Support for reference resolution via ResolutionContext
    - Deep copy functionality

    Reference Resolution:
        String field values can reference other NldNamedBaseModel instances
        by name, if those instances are available in the ResolutionContext.

        Example:
            # With this YAML:
            name: my_adapter
            field_adapter: base_adapter  # String reference

            # And this context:
            obj_dict = {"field_adapter": {"base_adapter": adapter_instance}}

            # The string "base_adapter" will be resolved to adapter_instance
            with ResolutionContext.with_registry(obj_dict):
                adapter = MyAdapter.from_yaml(yaml_content)
    """

    name: str

    @classmethod
    def from_yaml(cls, yaml_content: str) -> Self:
        """
        Read model instance from YAML string.

        Uses ResolutionContext for reference resolution. If no context is active,
        string references will not be resolved.

        Args:
            yaml_content: YAML content as string

        Returns:
            Instance of the model populated with data from the YAML string

        Raises:
            ValueError: If reference resolution errors occurred

        Example:
            >>> with ResolutionContext.with_registry(obj_dict):
            ...     model = MyModel.from_yaml(yaml_content)
        """
        data = yaml.safe_load(yaml_content)
        return cls.from_dict(from_dict=data)

    @classmethod
    def from_dict(cls, from_dict: dict[str, Any]) -> Self:
        """
        Read model instance from dictionary.

        Uses ResolutionContext for reference resolution. If no context is active,
        string references will not be resolved.

        Args:
            from_dict: Dictionary with model data

        Returns:
            Instance of the model populated with data from the dictionary

        Raises:
            ValueError: If reference resolution errors occurred

        Example:
            >>> with ResolutionContext.with_registry(obj_dict):
            ...     model = MyModel.from_dict(data)
        """
        resolved_data, reference_info = cls._resolve_references(data=from_dict)

        if ResolutionContext.has_errors():
            errors = ResolutionContext.get_errors()
            error_msg = (
                f"Failed to resolve references for {cls.__name__}:\n"
                + "\n".join(f"  - {err}" for err in errors)
            )
            ResolutionContext._context.errors = []
            raise ValueError(error_msg)

        instance = cls.model_validate(resolved_data)
        if reference_info:
            instance._resolved_references = reference_info
        return instance

    @classmethod
    def _resolve_references(
        cls,
        data: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Resolve string references to actual objects using ResolutionContext.

        Args:
            data: Dictionary with potential references

        Returns:
            Tuple of (resolved_data, reference_info) where reference_info
            tracks which fields were resolved from string references.
        """
        reference_info: dict[str, Any] = {}
        resolved_data = data.copy()

        for field_name, field_value in data.items():
            field_info = cls.model_fields.get(field_name)

            if isinstance(field_value, str):
                resolved_obj = cls._try_resolve_string_reference(
                    field_name=field_name,
                    field_value=field_value,
                )
                if resolved_obj is not None:
                    resolved_data[field_name] = resolved_obj
                    reference_info[field_name] = field_value

            elif isinstance(field_value, list):
                resolved_list, list_refs = cls._resolve_list_field(
                    field_info=field_info,
                    field_name=field_name,
                    field_value=field_value,
                )
                resolved_data[field_name] = resolved_list
                if list_refs:
                    reference_info[field_name] = list_refs

            elif isinstance(field_value, dict):
                resolved_dict, dict_refs = cls._resolve_dict_field(
                    field_info=field_info,
                    field_name=field_name,
                    field_value=field_value,
                )
                resolved_data[field_name] = resolved_dict
                if dict_refs:
                    reference_info[field_name] = dict_refs

        return resolved_data, reference_info

    @classmethod
    def _resolve_list_field(
        cls,
        field_info: Any,
        field_name: str,
        field_value: list[Any],
    ) -> tuple[list[Any], dict[int, str]]:
        """
        Resolve references in a list field.

        Args:
            field_info: Field metadata from model_fields
            field_name: Name of the field being resolved
            field_value: List value to resolve

        Returns:
            Tuple of (resolved_list, index_refs) where index_refs maps
            list indices to the original reference names.
        """
        if not field_info:
            return [
                (
                    cls._resolve_references(data=item)[0]
                    if isinstance(item, dict)
                    else item
                )
                for item in field_value
            ], {}

        element_type = cls._get_list_element_type(annotation=field_info.annotation)

        if element_type is None:
            return [
                (
                    cls._resolve_references(data=item)[0]
                    if isinstance(item, dict)
                    else item
                )
                for item in field_value
            ], {}

        index_refs: dict[int, str] = {}
        resolved_list = []
        for index, item in enumerate(field_value):
            if isinstance(item, str):
                resolved_obj = cls._try_resolve_by_type(
                    target_type=element_type,
                    field_value=item,
                    field_name=field_name,
                )
                if resolved_obj:
                    resolved_list.append(resolved_obj)
                    index_refs[index] = item
                else:
                    resolved_list.append(item)  # type: ignore[arg-type]
            elif isinstance(item, dict):
                if (
                    hasattr(element_type, "_resolve_references")
                    and hasattr(element_type, "__bases__")
                    and NldNamedBaseModel in element_type.__bases__
                ):
                    resolved_list.append(
                        element_type._resolve_references(data=item)[0],
                    )
                else:
                    resolved_list.append(cls._resolve_references(data=item)[0])
            else:
                resolved_list.append(item)

        return resolved_list, index_refs

    @classmethod
    def _resolve_dict_field(
        cls,
        field_info: Any,
        field_name: str,
        field_value: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """
        Resolve references in a dict field.

        Args:
            field_info: Field metadata from model_fields
            field_name: Name of the field being resolved
            field_value: Dict value to resolve

        Returns:
            Tuple of (resolved_dict, key_refs) where key_refs maps dict
            keys to the original reference names.
        """
        if not field_info:
            return cls._resolve_references(data=field_value)[0], {}

        value_type = cls._get_dict_value_type(annotation=field_info.annotation)

        if value_type is None:
            return cls._resolve_references(data=field_value)[0], {}

        key_refs: dict[str, str] = {}
        resolved_dict = {}
        for key, value in field_value.items():
            if isinstance(value, str):
                resolved_obj = cls._try_resolve_by_type(
                    target_type=value_type,
                    field_value=value,
                    field_name=field_name,
                )
                if resolved_obj:
                    resolved_dict[key] = resolved_obj
                    key_refs[key] = value
                else:
                    resolved_dict[key] = value  # type: ignore[assignment]
            elif isinstance(value, dict):
                if (
                    hasattr(value_type, "_resolve_references")
                    and hasattr(value_type, "__bases__")
                    and NldNamedBaseModel in value_type.__bases__
                ):
                    resolved_dict[key] = value_type._resolve_references(
                        data=value,
                    )[0]
                else:
                    resolved_dict[key] = cls._resolve_references(data=value)[0]
            else:
                resolved_dict[key] = value

        return resolved_dict, key_refs

    @classmethod
    def _get_list_element_type(cls, annotation: Any) -> type | None:
        """
        Extract element type from List[T] or Optional[List[T]] annotation.

        Args:
            annotation: Type annotation

        Returns:
            Element type if annotation is a list type, None otherwise
        """
        from typing import get_args, get_origin

        origin = get_origin(annotation)

        if origin is type(None):
            args = get_args(annotation)
            non_none_types = [arg for arg in args if arg is not type(None)]
            if len(non_none_types) == 1:
                annotation = non_none_types[0]
                origin = get_origin(annotation)

        if origin is list:
            args = get_args(annotation)
            if args:
                return args[0]  # type: ignore[no-any-return]

        return None

    @classmethod
    def _get_dict_value_type(cls, annotation: Any) -> type | None:
        """
        Extract value type from Dict[str, T] or Optional[Dict[str, T]].

        Args:
            annotation: Type annotation

        Returns:
            Value type if annotation is a dict type, None otherwise
        """
        from typing import get_args, get_origin

        origin = get_origin(annotation)

        if origin is type(None):
            args = get_args(annotation)
            non_none_types = [arg for arg in args if arg is not type(None)]
            if len(non_none_types) == 1:
                annotation = non_none_types[0]
                origin = get_origin(annotation)

        if origin is dict:
            args = get_args(annotation)
            if len(args) == 2:
                return args[1]  # type: ignore[no-any-return]

        return None

    @classmethod
    def _try_resolve_by_type(
        cls,
        target_type: type,
        field_value: str,
        field_name: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Resolve a string value as a reference to an object of a specific type.

        Args:
            target_type: Expected type of the referenced object
            field_value: String value that might be a reference
            field_name: Optional field name for error reporting

        Returns:
            Dictionary representation of resolved object, or None if not resolvable
        """
        if not hasattr(target_type, "__bases__"):
            return None

        if NldNamedBaseModel not in target_type.__bases__:
            return None

        from nld.utils.string_utils import camel_to_snake

        object_type = camel_to_snake(target_type.__name__)

        resolved_obj = ResolutionContext.get_object(
            object_type=object_type,
            object_name=field_value,
            field_name=field_name,
        )

        if resolved_obj is not None:
            return resolved_obj.model_dump()  # type: ignore[no-any-return]

        return None

    @classmethod
    def _try_resolve_string_reference(
        cls,
        field_name: str,
        field_value: str,
    ) -> dict[str, Any] | None:
        """
        Attempt to resolve a string value as a reference to another object.

        Args:
            field_name: Name of the field being resolved
            field_value: String value that might be a reference

        Returns:
            Dictionary representation of resolved object, or None if not a reference
        """
        field_info = cls.model_fields.get(field_name)
        if not field_info:
            return None

        annotation = field_info.annotation

        if hasattr(annotation, "__origin__") and annotation.__origin__ is type(None):  # type: ignore[union-attr]
            return None  # type: ignore[no-any-return]

        from typing import get_args, get_origin

        origin = get_origin(annotation)
        if origin is type(None):
            actual_type = annotation
        elif origin is not None:
            args = get_args(annotation)
            non_none_types = [arg for arg in args if arg is not type(None)]
            if len(non_none_types) == 1:
                actual_type = non_none_types[0]
            else:
                return None
        else:
            actual_type = annotation

        if not hasattr(actual_type, "__bases__"):
            return None

        if NldNamedBaseModel not in actual_type.__bases__:  # type: ignore[union-attr]
            return None

        from nld.utils.string_utils import camel_to_snake

        object_type = camel_to_snake(actual_type.__name__)  # type: ignore[union-attr]

        resolved_obj = ResolutionContext.get_object(
            object_type=object_type,
            object_name=field_value,
            field_name=field_name,
        )

        if resolved_obj is not None:
            return resolved_obj.model_dump()  # type: ignore[no-any-return]

        return None
