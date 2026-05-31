from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .execution_params_def import ExecutionParameterDefinition


def apply_default_values_to_parameters(
    parameters: dict[str, Any] | None,
    param_definitions: list["ExecutionParameterDefinition"],
) -> dict[str, Any]:
    """
    Apply default values from parameter definitions to the parameters dict.

    Args:
        parameters: Dictionary of parameters provided
        param_definitions: List of parameter definitions with possible defaults

    Returns:
        Dictionary with defaults applied for missing parameters
    """
    result = parameters.copy() if parameters is not None else {}
    for param_def in param_definitions:
        if param_def.name not in result and param_def.default_value is not None:
            result[param_def.name] = param_def.default_value
    return result
