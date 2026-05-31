"""
Step tracking utilities for managing FlowStepExecutionInfo lifecycle.

This module provides decorators and utilities to standardize the creation,
update, and management of FlowStepExecutionInfo objects in data flow tasks.
"""

from collections.abc import Callable
from functools import wraps
from typing import Any

from nld.utils.datetime_util import get_current_datetime

from .execution_info import (
    FlowStepExecutionInfo,
)


def track_flow_step[T](
    step_name: str | Callable[..., str],
    step_category: str | None = None,
    auto_append: bool = True,
    capture_exceptions: bool = True,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to automatically manage FlowStepExecutionInfo for a flow task method.

    The decorator:
    - Creates FlowStepExecutionInfo with proper lifecycle (started_at, ended_at)
    - Exposes step_info via self._current_step_info for metric updates
    - Handles exceptions and marks step as failed automatically
    - Appends step to self.flow_execution_info.steps

    Parameters:
        step_name: Name of the step. Can be a static string
            (e.g., "Extraction") or a callable that receives
            (self, *args, **kwargs) and returns a string for
            dynamic naming.
        auto_append: If True, automatically append step to flow_execution_info.steps
        capture_exceptions: If True, catch exceptions and mark step as failed

    Usage (static name):
        @track_flow_step(step_name="Extraction")
        def run_flow(self):
            data = self.extract_data()
            self._current_step_info.source_entries_in_success = len(data)

    Usage (dynamic name):
        @track_flow_step(
            step_name=lambda self, key, **kw: f"Process key {key}",
        )
        def process_key(self, key: str) -> None:
            ...

    Requirements:
        - Decorated method must be on a class with self.flow_execution_info attribute
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> T:
            # Validate that self has flow_execution_info
            if not hasattr(self, "flow_execution_info"):
                raise AttributeError(
                    f"Class {self.__class__.__name__} must have 'flow_execution_info' "
                    f"attribute to use @track_flow_step decorator"
                )

            # Resolve step name at runtime
            resolved_step_name = (
                step_name(self, *args, **kwargs) if callable(step_name) else step_name
            )

            # Create FlowStepExecutionInfo
            step_info = FlowStepExecutionInfo(
                flow_uid=self.flow_execution_info.flow_uid,
                step_name=resolved_step_name,
                step_category=step_category,
                started_at=get_current_datetime(),
            )

            # Expose step_info for method to update metrics
            self._current_step_info = step_info

            try:
                # Execute the decorated method
                result = func(self, *args, **kwargs)

                # Mark as completed on success
                step_info.update_execution_status_to_completed()

                return result

            except Exception as e:
                if capture_exceptions:
                    # Mark as failed and re-raise
                    step_info.update_execution_status_to_failed(str(e))
                    raise
                else:
                    # Re-raise without marking as failed
                    raise

            finally:
                # Always append step (even on failure for audit trail)
                if auto_append:
                    if self.flow_execution_info.steps is None:
                        self.flow_execution_info.steps = []
                    self.flow_execution_info.steps.append(step_info)

                # Clean up temporary attribute
                if hasattr(self, "_current_step_info"):
                    delattr(self, "_current_step_info")

        return wrapper

    return decorator
