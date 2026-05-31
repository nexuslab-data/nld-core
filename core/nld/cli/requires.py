import logging
from collections.abc import Callable
from functools import update_wrapper
from typing import Any

from click import Context

from nld.cli.cli_events import CommandCompleted, CommandRuntimeError
from nld.cli.cli_exceptions import ExceptionExit
from nld.logging import EventLevel, LoggerManager, log_event_default
from nld.task.context import NldExecutionContext, TaskRequest


def _init_logger(
    logger_formatter: logging.Formatter,
    event_level: EventLevel = EventLevel.INFO,
) -> None:
    LoggerManager(level=event_level, formatter=logger_formatter)


_DEFAULT_LOGGER_FORMATTER = logging.Formatter(
    "[%(asctime)s] [%(levelname)s] - %(message)s"
)


def pre_processing(
    func: Any = None,
    logger_formatter: logging.Formatter | None = None,
    with_project: bool = False,
    completion_label: str | None = None,
) -> Callable[..., Any]:
    """Handles all preprocessing tasks for click commands.

    This decorator must be the first decorator to declare. It initializes
    the logger manager, context object dictionary, and execution information.

    Args:
        func: The function to wrap
        logger_formatter: The logger formatter to use
        with_project: Whether to initialize the project in the execution context
        completion_label: Custom label for the completion message
    """

    def decorator(f: Any):  # type: ignore
        def wrapper(*args, **kwargs):  # type: ignore
            ctx = args[0]
            assert isinstance(ctx, Context)

            formatter = logger_formatter or _DEFAULT_LOGGER_FORMATTER
            log_level_name = ctx.params.pop("log_level", "INFO")
            _init_logger(
                logger_formatter=formatter,
                event_level=EventLevel[log_level_name.upper()],
            )

            command_path_parts: list[str] = []
            current_ctx: Context | None = ctx
            while current_ctx is not None:
                if current_ctx.info_name is not None:
                    command_path_parts.insert(0, current_ctx.info_name)
                current_ctx = current_ctx.parent

            if len(command_path_parts) > 1:
                execution_name = " ".join(command_path_parts[1:])
            else:
                execution_name = (
                    command_path_parts[0]
                    if command_path_parts
                    else (ctx.command.name or "unknown")
                )

            task_request = TaskRequest(
                execution_name=execution_name,
                params=ctx.params,
                extra_args=ctx.args,
                completion_label=completion_label,
            )

            NldExecutionContext(
                task_request=task_request,
                with_project=with_project,
            ).set_current()

            ctx.run_params = {}  # type: ignore[attr-defined]

            return f(*args, **kwargs)

        return update_wrapper(wrapper, f)

    if func is not None:
        return decorator(func)  # type: ignore[no-any-return]
    return decorator


def manage_cli_exception(
    func: Any = None,
    silent_completion: bool = False,
) -> Any:
    """Handles all exception handling for click commands.

    This decorator must be used before any other decorators that may throw
    an exception.

    Args:
        func: The function to wrap
        silent_completion: When True, skip logging the CommandCompleted event
    """

    def decorator(f: Any) -> Any:
        def wrapper(*args, **kwargs):  # type: ignore
            caught_exception: Exception | None = None
            exception_occurred = False
            try:
                success = f(*args, **kwargs)
            except (RuntimeError, Exception) as e:
                exception_occurred = True
                caught_exception = e
                log_event_default(CommandRuntimeError(e=e))
                raise ExceptionExit(e) from e
            finally:
                execution_context = NldExecutionContext.get_current()
                if execution_context is not None:
                    exec_info = execution_context.exec_info
                    if exception_occurred:
                        exec_info.update_execution_status_to_failed(
                            error_message=str(caught_exception),
                        )
                    else:
                        exec_info.update_execution_status_to_completed()
                    if not silent_completion:
                        log_event_default(
                            CommandCompleted(exec_info=exec_info),
                        )
            return success

        return update_wrapper(wrapper, f)

    if func is not None:
        return decorator(func)
    return decorator
