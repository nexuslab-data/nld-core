from typing import Any, ClassVar

import click

from nld.flow.deploy.flow_deploy_executor import FlowDeployExecutor, FlowDeployResult
from nld.flow.deploy.flow_deploy_manifest import DeployManifest
from nld.flow.deploy.flow_deploy_planner import FlowDeployPlanner
from nld.parameters.execution_params_def import ExecutionParameterDefinition
from nld.task.base import StandardTask


class FlowDeployExecuteTask(StandardTask):
    """Orchestrates ``nld flow deploy execute``.

    The command supports two execution modes:

    - **Default — in-memory plan**: build a ``DeployManifest`` from the
      current entity state via ``FlowDeployPlanner``, optionally prompt
      the user, and hand the manifest to ``FlowDeployExecutor`` for
      apply. Backfill is suppressed by default; ``--with-backfill`` opts
      in.
    - **``--from-plan`` — manifest-based**: skip the planner; hand a
      pre-existing manifest path (or trigger auto-discovery) to
      ``FlowDeployExecutor``.

    The orchestrator is the single place that knows about both the
    planner and the executor. Each underlying task remains responsible
    for one thing: ``FlowDeployPlanner`` produces manifests,
    ``FlowDeployExecutor`` applies them.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(
            name="from_plan",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="interactive",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="manifest_path",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="no_backfill",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="plan_only",
            mandatory=False,
        ),
        ExecutionParameterDefinition(
            name="with_backfill",
            mandatory=False,
        ),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        from_plan: bool = False,
        interactive: bool = True,
        manifest_path: str | None = None,
        no_backfill: bool = False,
        plan_only: bool = False,
        with_backfill: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        # --manifest-path implies --from-plan: pointing at a specific
        # manifest file only makes sense in manifest mode.
        if manifest_path is not None:
            from_plan = True
        if plan_only and from_plan:
            raise ValueError(
                "--plan-only is mutually exclusive with --from-plan "
                "(and with --manifest-path, which implies --from-plan). "
                "--plan-only generates a fresh deployment plan from the "
                "current state — equivalent to `nld flow deploy plan` — "
                "while --from-plan applies an already-generated manifest.",
            )
        if with_backfill and from_plan:
            raise ValueError(
                "--with-backfill is only valid in the default in-memory "
                "mode of `deploy execute`. In --from-plan mode, the "
                "backfill strategy is governed by the manifest entries; "
                "use --no-backfill to override and skip.",
            )
        if with_backfill and no_backfill:
            raise ValueError(
                "--with-backfill and --no-backfill are mutually exclusive.",
            )
        # In the default in-memory mode, backfill is opt-in via
        # --with-backfill. The default is no backfill so a one-shot
        # `deploy execute` never accidentally rewrites historical data.
        if not from_plan and not with_backfill:
            no_backfill = True
        self._from_plan = from_plan
        self._interactive = interactive
        self._manifest_path = manifest_path
        self._no_backfill = no_backfill
        self._plan_only = plan_only

    def run(
        self,
        **kwargs: Any,
    ) -> list[FlowDeployResult]:
        """Route to the in-memory or manifest-based pipeline."""
        if self._from_plan:
            return self._run_from_plan()
        return self._run_in_memory_plan()

    def _run_in_memory_plan(self) -> list[FlowDeployResult]:
        """Build a manifest in memory and (optionally) execute it.

        When ``--plan-only`` is set, the planner persists the manifest
        to ``.deployments/flows/`` and the orchestrator exits — equivalent
        to ``nld flow deploy plan``. Otherwise, the manifest is held in
        memory, the user is optionally prompted, and the executor applies
        it.
        """
        planner = FlowDeployPlanner(
            interactive=self._interactive,
            no_backfill=self._no_backfill,
            persist_manifest=self._plan_only,
        )
        manifest = planner.run()

        if self._plan_only:
            self.log_info(
                "--plan-only set: manifest generated, no execution.",
            )
            return []

        if not manifest.flows and not manifest.structures:
            self.log_info("No changes detected — nothing to deploy")
            return []

        if self._interactive and not self._confirm_deployment(manifest=manifest):
            self.log_info("Deployment cancelled by user")
            return []

        executor = FlowDeployExecutor(
            manifest=manifest,
            no_backfill=self._no_backfill,
        )
        return executor.run()

    def _run_from_plan(self) -> list[FlowDeployResult]:
        """Apply a pre-generated manifest via the executor.

        Either ``--manifest-path`` was provided (apply that file) or the
        executor will auto-discover manifests under ``.deployments/flows/``.
        """
        executor = FlowDeployExecutor(
            manifest_path=self._manifest_path,
            no_backfill=self._no_backfill,
        )
        return executor.run()

    def _confirm_deployment(
        self,
        manifest: DeployManifest,
    ) -> bool:
        """Prompt the user to confirm an in-memory deployment plan."""
        flow_count = len(manifest.flows)
        structure_count = len(manifest.structures)
        self.log_info(
            f"In-memory plan: {flow_count} flow change(s), "
            f"{structure_count} structure change(s). "
            f"Backfill suppressed: {self._no_backfill}.",
        )
        return click.confirm(
            "Proceed with deployment?",
            default=False,
        )
