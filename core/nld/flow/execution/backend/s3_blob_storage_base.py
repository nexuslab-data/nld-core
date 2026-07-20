import abc
from typing import ClassVar

from nld.connector.s3_blob_storage import S3ObjectStorageConnector
from nld.flow.backend.s3_blob_storage import S3BackendMixin
from nld.flow.execution.execution_info import (
    FlowExecutionHistory,
    FlowExecutionInfo,
    FlowStepExecutionInfo,
)
from nld.flow.execution.manager import (
    ExecutionBackendStateManager,
    steps_from_loaded_executions,
)


class S3ExecutionBackendStateManagerBase(
    S3BackendMixin,
    ExecutionBackendStateManager[S3ObjectStorageConnector],
    abc.ABC,
):
    """
    Base class for S3 execution backend state managers.

    Combines S3BackendMixin functionality with ExecutionBackendStateManager
    for different engine implementations (pydantic, duckdb).
    """

    param_definitions = [*S3BackendMixin.s3_param_definitions]

    #: Default number of executions returned by ``get_execution_history``
    #: when the caller does not pass an explicit ``limit``. S3 stores the
    #: whole history in a single blob, so without a cap inspecting a
    #: long-lived production flow would materialise (and render) its entire
    #: history. The by-uid lookup (``get_execution_info``) is intentionally
    #: not bounded by this so older executions remain reachable.
    DEFAULT_HISTORY_LIMIT: ClassVar[int] = 10

    def _get_steps_for(self, flow_uid: str) -> list[FlowStepExecutionInfo]:
        """Return the inline steps for an execution stored as a blob."""
        execution_state, execution_history = self.retrieve_latest_execution_state()
        return steps_from_loaded_executions(
            flow_uid=flow_uid,
            execution_state=execution_state,
            execution_history=execution_history,
        )

    def get_execution_history(
        self, *, limit: int | None = None, with_steps: bool = True
    ) -> FlowExecutionHistory:
        """Read the execution history from a single state download.

        The generic implementation resolves each execution's steps through
        ``_get_steps_for``, which for an S3 backend re-downloads the whole
        state+history blob once per execution — ``O(N)`` downloads of the
        same two files. S3 already stores each execution's steps inline in
        the history blob, so here we download once and use the steps that
        are already loaded.

        When no explicit ``limit`` is given the listing is capped at
        ``DEFAULT_HISTORY_LIMIT`` so inspecting a long-lived production flow
        does not pull and render its entire history.
        """
        effective_limit = self.DEFAULT_HISTORY_LIMIT if limit is None else limit

        _, history = self.retrieve_latest_execution_state()
        executions = sorted(
            history.executions,
            key=lambda info: info.started_at or "",
            reverse=True,
        )
        if effective_limit is not None:
            executions = executions[:effective_limit]
        if not with_steps:
            for info in executions:
                info.steps = None
        return FlowExecutionHistory(executions=executions)

    def get_execution_info(
        self, flow_uid: str, *, with_steps: bool = True
    ) -> FlowExecutionInfo | None:
        """Return a single execution by uid from a single state download.

        Not subject to ``DEFAULT_HISTORY_LIMIT``: the full recorded history
        (and the latest-state slot) is scanned so an execution older than
        the most recent runs can still be inspected by uid. Steps are read
        from the inline blob, so no extra download happens.
        """
        execution_state, history = self.retrieve_latest_execution_state()
        info = next(
            (
                candidate
                for candidate in (
                    execution_state.last_processed,
                    *history.executions,
                )
                if candidate is not None and candidate.flow_uid == flow_uid
            ),
            None,
        )
        if info is not None and not with_steps:
            info.steps = None
        return info
