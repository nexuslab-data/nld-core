import sys
from collections.abc import Callable
from typing import Any

from nld.logging import EventLevel, LoggerManager, log_event_default
from nld.task.context import NldExecutionContext, TaskRequest
from nld.task.task_events import (
    ExecutionCompleted,
    ExecutionRuntimeError,
    ExecutionStarted,
)


def _init_logger(event_level: EventLevel | None = None) -> None:
    """Initialize the logger manager with the specified event level."""
    if event_level is not None:
        LoggerManager(level=event_level)
    else:
        LoggerManager(level=EventLevel.INFO)


def _parse_module_args(args: list[str] | None = None) -> dict[str, Any]:
    """
    Parse command-line arguments in the format --key=value or --key value.

    Args:
        args: Optional list of command-line arguments. If None, uses sys.argv.

    Returns:
        Dictionary of parsed arguments with keys normalized (hyphens replaced
        with underscores).
    """
    if args is None:
        args = sys.argv[1:]

    parsed_args: dict[str, Any] = {}
    i = 0
    while i < len(args):
        arg = args[i]

        if arg.startswith("--"):
            if "=" in arg:
                key, value = arg[2:].split("=", 1)
                key = key.replace("-", "_")
                parsed_args[key] = value
                i += 1
            else:
                key = arg[2:].replace("-", "_")
                if i + 1 < len(args) and not args[i + 1].startswith("--"):
                    parsed_args[key] = args[i + 1]
                    i += 2
                else:
                    parsed_args[key] = True
                    i += 1
        else:
            i += 1

    return parsed_args


def _get_execution_name_from_module() -> str:
    """
    Extract execution name from the module being executed.

    Returns:
        Module name extracted from sys.argv[0] or '__main__' if not available.
    """
    if len(sys.argv) > 0:
        module_path = sys.argv[0]
        if module_path.endswith(".py"):
            module_path = module_path[:-3]
        parts = module_path.replace("/", ".").replace("\\", ".").split(".")
        return ".".join(parts[-2:]) if len(parts) > 1 else parts[-1]
    return "__main__"


def initialize_module_execution(
    execution_name: str | None = None,
    params: dict[str, Any] | None = None,
    extra_args: list[str] | None = None,
    event_level: EventLevel | None = None,
) -> NldExecutionContext:
    """
    Initialize execution context for a Python module run.

    This function provides similar functionality to the CLI pre_processing
    decorator but for module execution (e.g., python -m module.name --arg1
    value1).

    Args:
        execution_name: Optional custom execution name. If not provided, will
                        be extracted from sys.argv or module path.
        params: Optional dictionary of parameters to pass to the task.
        extra_args: Optional list of extra arguments. If not provided, will
                    be parsed from sys.argv.
        event_level: Optional logging event level. Defaults to INFO.

    Returns:
        Initialized NldExecutionContext set as the current context.

    Example:
        ```python
        from nld.task.module_init import (
            initialize_module_execution,
            run_with_module_exception_handling,
        )

        def main():
            context = initialize_module_execution()
            # Your execution logic here
            return True

        if __name__ == "__main__":
            run_with_module_exception_handling(main)
        ```
    """
    _init_logger(event_level=event_level)

    if execution_name is None:
        execution_name = _get_execution_name_from_module()

    if params is None:
        params = _parse_module_args(extra_args)
        extra_args_list = None
    else:
        extra_args_list = extra_args

    task_request = TaskRequest(
        execution_name=execution_name,
        params=params,
        extra_args=extra_args_list,
    )

    context = NldExecutionContext(task_request=task_request)
    context.set_current()

    log_event_default(ExecutionStarted(exec_info=context.exec_info))

    return context


def run_with_module_exception_handling(
    func: Callable[[], Any],
    exit_on_error: bool = True,
) -> Any:
    """
    Execute a function with proper exception handling and logging.

    This function provides similar functionality to the CLI manage_cli_exception
    decorator but for module execution.

    Args:
        func: The function to execute. Should return a success indicator
              (True/False) or any value.
        exit_on_error: If True, calls sys.exit(1) on error. If False, re-raises
                       the exception.

    Returns:
        The return value of func if successful.

    Raises:
        Exception: Re-raises the caught exception if exit_on_error is False.
    """
    success = False
    result = None

    caught_exception: Exception | None = None
    try:
        result = func()
        success = True if result is None else bool(result)
    except (RuntimeError, Exception) as e:
        caught_exception = e
        log_event_default(ExecutionRuntimeError(e=e))
        if exit_on_error:
            sys.exit(1)
        else:
            raise
    finally:
        context = NldExecutionContext.get_current()
        if context is not None:
            exec_info = context.exec_info
            if success:
                exec_info.update_execution_status_to_completed()
            else:
                exec_info.update_execution_status_to_failed(
                    error_message=str(caught_exception) if caught_exception else None,
                )
            log_event_default(ExecutionCompleted(exec_info=exec_info))
            NldExecutionContext.clear_current()

    return result
