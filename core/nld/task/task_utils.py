from typing import Any

from .base import BaseTask


def execute_task(
    task_type: type["BaseTask"],
    extra_init_params: dict[str, Any] | None = None,
) -> Any:
    """Construct and run a task using the current execution context.

    Args:
        task_type: The ``BaseTask`` subclass to instantiate.
        extra_init_params: Optional extra keyword arguments forwarded to
            the task's ``__init__`` in addition to the CLI-derived
            parameters. Use this to inject Python-only dependencies
            (callbacks, services) the task needs but cannot be parsed
            from CLI flags — keeping the task itself free of CLI-
            specific imports.
    """
    from nld.task.context import NldExecutionContext

    # --- Step 1: Get the current task execution context
    nld_execution_context = NldExecutionContext.require_current()

    # --- Step 2: Build init and run parameters based on task request and task type
    task_request_parameters = nld_execution_context.task_request.get_parameters()
    init_params = {
        key: value
        for key, value in task_request_parameters.items()
        if key in task_type.get_init_params_keys()
    }
    run_params = {
        key: value
        for key, value in task_request_parameters.items()
        if key in task_type.get_run_params_keys()
    }

    # --- Step 3: Check init and run parameters dict coherence
    task_type.check_init_params_dict(init_params)
    task_type.check_run_params_dict(run_params)

    if extra_init_params is not None:
        init_params.update(extra_init_params)

    # --- Step 4: Execute the task
    task_inst = task_type(**init_params)
    result = task_inst.run(**run_params)
    return result
