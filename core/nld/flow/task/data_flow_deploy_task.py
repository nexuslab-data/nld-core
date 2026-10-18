import sys
from typing import Any, ClassVar

import click

from nld.flow.alerting import FlowAlertItem, FlowAlertLevel, FlowExecutionOutcome
from nld.flow.deploy.flow_change_set import FlowChangeSet
from nld.flow.deploy.flow_deploy_executor import (
    FLOW_DEPLOY_COMMAND,
    FlowDeployExecutor,
    FlowDeployResult,
)
from nld.flow.deploy.flow_deploy_planner import FlowDeployPlanner
from nld.flow.exceptions import FlowDeployFailedException
from nld.flow.utils import FlowExecStatus
from nld.parameters.execution_params_def import ExecutionParameterDefinition
from nld.pydantic import NldNamespace
from nld.task.base import StandardTask


class FlowDeployTask(StandardTask):
    """Orchestrates ``nld flow deploy``.

    Deployment is stateless: the change set is always
    computed in memory against the live target by ``FlowDeployPlanner``
    and applied immediately by ``FlowDeployExecutor``. Nothing is
    persisted or replayed. With ``--preview`` the computed change set
    (including the structure DDL) is printed and nothing is applied.

    The orchestrator is the single place that knows about both the
    planner and the executor. Each underlying task remains responsible
    for one thing: ``FlowDeployPlanner`` computes change sets,
    ``FlowDeployExecutor`` applies them.

    A deploy that leaves any structure or flow failed raises
    ``FlowDeployFailedException`` once the run is recorded, so the
    command exits non-zero; every failed deploy is alerted through the
    project's alerting transports (see ``report_deploy_failure``).
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(
            name="adopt",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="allow_drift",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="downstream",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="interactive",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="name",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="namespace",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="output",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="preview",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="rebuild",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="upstream",
            mandatory=False,
        ),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        adopt: bool = False,
        allow_drift: bool = False,
        downstream: bool = False,
        interactive: bool = True,
        name: str | None = None,
        namespace: str | None = None,
        output: str | None = None,
        preview: bool = False,
        rebuild: bool = False,
        upstream: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._adopt = adopt
        self._allow_drift = allow_drift
        self._downstream = downstream
        self._interactive = interactive
        self._name = name
        self._namespace = namespace
        self._output = output
        self._preview = preview
        self._rebuild = rebuild
        self._upstream = upstream

    def run(
        self,
        **kwargs: Any,
    ) -> list[FlowDeployResult] | FlowChangeSet:
        """Compute the change set, then preview or apply it.

        With ``preview=True`` the computed change set is printed,
        optionally written as JSON (``output``), and returned so
        callers (CI gates, the CLI's changes-pending exit code) can
        consume it structurally instead of scraping log lines.
        """
        if self._preview:
            change_set = self._build_planner().run()
            self._print_change_set(change_set=change_set)
            self._write_change_set_output(change_set=change_set)
            return change_set

        try:
            return self._deploy()
        except Exception as ex:
            self.report_deploy_failure(error=ex)
            raise

    def _build_planner(self) -> FlowDeployPlanner:
        """Build the planner computing the change set of this deploy."""
        return FlowDeployPlanner(
            adopt=self._adopt,
            allow_drift=self._allow_drift,
            downstream=self._downstream,
            name=self._name,
            namespace=self._namespace,
            rebuild=self._rebuild,
            upstream=self._upstream,
        )

    def _deploy(self) -> list[FlowDeployResult]:
        """Plan and apply the change set, raising when any part failed.

        The executor records a run with failures as partial or failed
        and returns normally, so that every independent change still
        lands; the command itself must then fail, or a scheduler reads
        a half-applied release as a successful one.
        """
        planner = self._build_planner()
        change_set = planner.run()

        if change_set.is_empty():
            self.log_info("No changes detected — nothing to deploy")
            return []

        if self._interactive and not self._confirm_deployment(change_set=change_set):
            self.log_info("Deployment cancelled by user")
            return []

        # The executor reuses the planner's per-(connection, schema)
        # managers — and their prefetched snapshots — so applying
        # never recomputes the live state planning already read.
        executor = FlowDeployExecutor(
            change_set=change_set,
            adopt=self._adopt,
            allow_drift=self._allow_drift,
            deploy_target_factory=planner.deploy_target_factory,
            rebuild=self._rebuild,
        )
        result = executor.run()
        if result.has_failures:
            raise FlowDeployFailedException(
                deployment_id=result.deployment_id,
                failed_flows=result.failed,
                failed_structures=result.structures_failed,
                status=result.status,
            )
        return [result]

    def report_deploy_failure(self, error: Exception) -> None:
        """Alert on a failed deploy and print the outcome line. Never raises.

        A deploy runs unattended in a scheduler pod, where an error only
        written to the pod log goes unread and a release goes out half
        applied. The alerting in force is the deployed namespace's, the
        root's for a whole-project deploy. Losing the alert must not hide
        the deploy error itself, so a problem here is only logged.
        """
        try:
            self._report_deploy_failure(error=error)
        except Exception as ex:
            self.log_warn(f"Deploy failure could not be reported: {ex}")

    def _report_deploy_failure(self, error: Exception) -> None:
        service = self.execution_context.alerting_provider.for_flow(
            flow_namespace=self._namespace or NldNamespace.ROOT_VALUE,
        )
        deploy_failure = error if isinstance(error, FlowDeployFailedException) else None
        alerted = False
        if service.should_alert(FlowAlertLevel.FAILED):
            alerted = service.notify(
                service.build_command_alert(
                    command=self._describe_command(),
                    error=error,
                    items=self._build_failure_items(deploy_failure=deploy_failure),
                    run_id=(
                        deploy_failure.deployment_id
                        if deploy_failure is not None
                        else self.execution_context.exec_info.uuid
                    ),
                    summary=(
                        deploy_failure.headline if deploy_failure is not None else None
                    ),
                ),
            )
        outcome_line = service.build_outcome_line(
            FlowExecutionOutcome(
                alert_level=FlowAlertLevel.FAILED,
                alerted=alerted,
                execution_status=FlowExecStatus.FAILED,
            ),
        )
        if outcome_line is not None:
            sys.stdout.write(outcome_line + "\n")
            sys.stdout.flush()

    def _describe_command(self) -> str:
        """The deploy command line, scoped as it was requested."""
        command = FLOW_DEPLOY_COMMAND
        if self._namespace is not None:
            command += f" --namespace {self._namespace}"
        if self._name is not None:
            command += f" --name {self._name}"
        return command

    @staticmethod
    def _build_failure_items(
        deploy_failure: FlowDeployFailedException | None,
    ) -> list[FlowAlertItem]:
        """One alert line per structure and flow that failed to deploy."""
        if deploy_failure is None:
            return []
        return [
            FlowAlertItem(
                detail=detail,
                label=f"{kind} {name}",
            )
            for kind, failures in (
                ("structure", deploy_failure.failed_structures),
                ("flow", deploy_failure.failed_flows),
            )
            for name, detail in failures.items()
        ]

    def _write_change_set_output(
        self,
        change_set: FlowChangeSet,
    ) -> None:
        """Write the previewed change set as JSON when requested."""
        if self._output is None:
            return
        change_set.write_json_file(file_path=self._output)
        self.log_info(f"Change set written to {self._output}")

    def _print_change_set(
        self,
        change_set: FlowChangeSet,
    ) -> None:
        """Print the computed change set without applying anything."""
        if change_set.is_empty():
            self.log_info("[PREVIEW] No changes detected — empty change set")
            return

        for pending in change_set.pending_change_files:
            self.log_info(
                f"[PREVIEW] Pending change file: {pending.change_id}",
            )
        for flow_entry in change_set.flows:
            self.log_info(
                f"[PREVIEW] Flow '{flow_entry.namespace}.{flow_entry.flow_name}': "
                f"{flow_entry.action}",
            )
        for structure_entry in change_set.structures:
            self.log_info(
                f"[PREVIEW] Structure "
                f"'{structure_entry.namespace}.{structure_entry.structure_name}': "
                f"{structure_entry.action}",
            )
            if structure_entry.planning_error is not None:
                self.log_error(
                    f"[PREVIEW] Planning failed: {structure_entry.planning_error}",
                )
            for statement in structure_entry.ddl_statements:
                self.log_info(f"[PREVIEW] Would execute: {statement}")

    def _confirm_deployment(
        self,
        change_set: FlowChangeSet,
    ) -> bool:
        """Prompt the user to confirm applying the change set."""
        flow_count = len(change_set.flows)
        structure_count = len(change_set.structures)
        self.log_info(
            f"Change set: {flow_count} flow change(s), "
            f"{structure_count} structure change(s).",
        )
        return click.confirm(
            "Proceed with deployment?",
            default=False,
        )
