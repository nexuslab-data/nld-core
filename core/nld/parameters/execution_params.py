import json
from typing import Any

from nld.pydantic import NldBaseModel, NldNamedBaseModel
from nld.utils import ModuleLoader

EXECUTION_PARAMETER_TYPE_CONTEXT = "context"
EXECUTION_PARAMETER_TYPE_KEYWORDS = [EXECUTION_PARAMETER_TYPE_CONTEXT]

EXECUTION_PARAMETER_CONTEXT_OBJECTS_KEY = "objects"


class ExecutionParameter(NldNamedBaseModel):
    runtime: bool = False
    type: str | None = None
    value: str | int | float | bool | dict[str, Any] | list[dict[str, Any]] | None = (
        None
    )


def create_model_dict(
    execution_param_list: list[ExecutionParameter],
    additional_paths: list[str] | None = None,
    param_type_hints: dict[str, type[Any]] | None = None,
) -> dict[str, Any]:
    """
    Create a dictionary of parameter values with type instantiation.

    Args:
        execution_param_list: List of execution parameters to process.
        additional_paths: Optional list of additional module paths to try when
            importing parameter types. Enables using short type names.
        param_type_hints: Optional dictionary mapping parameter names to their
            types, typically from task class introspection. Used when type is
            not specified in the execution parameter.

    Returns:
        Dictionary mapping parameter names to their instantiated values.
    """
    param_dict: dict[str, Any] = {}
    loader = ModuleLoader(additional_paths=additional_paths)
    type_hints = param_type_hints or {}

    for execution_param in execution_param_list:
        if execution_param.runtime:
            continue

        param_name = execution_param.name
        explicit_type = execution_param.type

        # Determine the class type to use for instantiation
        class_type = _resolve_param_type(
            explicit_type=explicit_type,
            param_name=param_name,
            type_hints=type_hints,
            loader=loader,
            additional_paths=additional_paths,
        )

        # If no type resolved, keep value as-is
        if class_type is None:
            param_dict[param_name] = execution_param.value
            continue

        # Validate it's an NldBaseModel subclass
        if not issubclass(class_type, NldBaseModel):
            raise ValueError(
                f"Execution parameter class {class_type} must inherit from NldBaseModel"
            )
        if execution_param.value is None:
            raise ValueError("Execution parameter value is mandatory for custom type")
        if isinstance(execution_param.value, str | int | float | bool):
            raise ValueError(
                f"Execution parameter value for '{param_name}' must be a dict or list, "
                f"not a scalar, when using custom type {class_type}"
            )

        # Instantiate the parameter value using the class type
        param_dict[param_name] = _instantiate_param_value(
            class_type=class_type,
            value=execution_param.value,
        )

    return param_dict


def _resolve_param_type(
    explicit_type: str | None,
    param_name: str,
    type_hints: dict[str, type[Any]],
    loader: ModuleLoader,
    additional_paths: list[str] | None,
) -> type[Any] | None:
    """
    Resolve the type for a parameter from explicit type or introspection.

    Priority order:
    1. Explicit type "Any" → returns None (keep value as-is)
    2. Explicit type string → load class from path
    3. Type from introspection hints (only NldBaseModel subclasses)
    4. No type available → returns None (keep value as-is)
    """
    # Case 1: Explicit "Any" or "str" type - keep value as-is
    if explicit_type in ("Any", "str"):
        return None

    # Case 2: Explicit type string provided - load the class
    if explicit_type is not None:
        _, class_type = loader.load_class(
            path_or_class_name=explicit_type,
            try_to_import_from_additional_paths=bool(additional_paths),
        )
        return class_type

    # Case 3: Try to get type from introspection hints
    if param_name in type_hints:
        hint_type = type_hints[param_name]
        # Only use introspected type if it's an NldBaseModel subclass
        if isinstance(hint_type, type) and issubclass(hint_type, NldBaseModel):
            return hint_type

    # Case 4: No type available - keep value as-is
    return None


def _instantiate_param_value(
    class_type: type[NldBaseModel],
    value: dict[str, Any] | list[dict[str, Any]],
) -> NldBaseModel | list[NldBaseModel]:
    """Instantiate parameter value using the resolved class type."""
    if isinstance(value, list):
        return [class_type.from_dict(item) for item in value]
    elif isinstance(value, dict):
        return class_type.from_dict(value)
    else:
        raise ValueError(f"Execution parameter value is not managed for {value}")


def _parse_cli_value(raw_value: str) -> Any:
    """Parse a CLI string value as JSON, falling back to the raw string."""
    try:
        return json.loads(raw_value)
    except (json.JSONDecodeError, TypeError):
        return raw_value


def resolve_runtime_params(
    runtime_params: list[ExecutionParameter],
    cli_values: dict[str, Any],
    param_type_hints: dict[str, type[Any]] | None = None,
    additional_paths: list[str] | None = None,
) -> dict[str, Any]:
    """
    Resolve runtime parameters from CLI values with type instantiation.

    Runtime parameters are declared in flow YAML with ``runtime: true`` and
    their values are provided at execution time via CLI arguments. String
    values from CLI are parsed as JSON before type resolution.

    Args:
        runtime_params: List of runtime execution parameters to resolve.
        cli_values: Dictionary of CLI-provided values keyed by parameter name.
        param_type_hints: Optional type hints from task class introspection.
        additional_paths: Optional additional module paths for type loading.

    Returns:
        Dictionary mapping parameter names to their resolved values.

    Raises:
        ValueError: If a mandatory runtime parameter is missing from CLI.
    """
    resolved: dict[str, Any] = {}
    loader = ModuleLoader(additional_paths=additional_paths)
    type_hints = param_type_hints or {}

    for param in runtime_params:
        param_name = param.name

        if param_name not in cli_values:
            continue

        raw_value = cli_values[param_name]

        # Parse JSON strings from CLI input
        if isinstance(raw_value, str):
            raw_value = _parse_cli_value(raw_value)

        # Resolve the type for this parameter
        class_type = _resolve_param_type(
            explicit_type=param.type,
            param_name=param_name,
            type_hints=type_hints,
            loader=loader,
            additional_paths=additional_paths,
        )

        if class_type is None:
            resolved[param_name] = raw_value
            continue

        if not issubclass(class_type, NldBaseModel):
            raise ValueError(
                f"Runtime parameter class {class_type} must inherit from NldBaseModel"
            )
        if raw_value is None:
            raise ValueError(
                f"Runtime parameter value for '{param_name}' cannot be None "
                f"when using custom type {class_type}"
            )
        if isinstance(raw_value, str):
            raise ValueError(
                f"Runtime parameter value for '{param_name}' must be a dict or list, "
                f"not a string, when using custom type {class_type}"
            )

        resolved[param_name] = _instantiate_param_value(
            class_type=class_type,
            value=raw_value,
        )

    return resolved
