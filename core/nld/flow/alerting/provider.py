import os
from collections.abc import Mapping
from typing import TYPE_CHECKING

from nld.flow.alerting.models import FlowAlertingRuntimeSettings
from nld.flow.alerting.registry import get_flow_alert_transport_registry
from nld.flow.alerting.service import FlowAlertingService
from nld.flow.alerting.transports.base import FlowAlertTransport
from nld.utils.mixin import NldMixIn

# nld.project imports the flow config, which declares the transport
# manifests of this package: the project and scheduling types are typing-only
# here and the policy is imported when first needed.
if TYPE_CHECKING:
    from nld.flow.alerting.registry import FlowAlertTransportRegistry
    from nld.project import Project
    from nld.scheduling.config import AlertingConfig, SchedulingNamespaceConfig


class FlowAlertingProvider(NldMixIn):
    """The execution context's entry point to alerting.

    One provider per execution context: it reads the runtime side of
    alerting from the environment once, knows the project's namespace-scoped
    declarations, and hands each flow the ``FlowAlertingService`` in force
    for its namespace — with the declared transports that this environment
    actually configures.

    ``scheduling_config`` is the project's namespace-scoped ``scheduling``
    block (None outside a project: nothing is ever declared, no flow
    alerts); ``environ`` is where the transports' secrets and the runtime
    settings come from (the process environment by default, a mapping in
    tests); ``registry`` names the technologies available (the process-wide
    registry by default).
    """

    def __init__(
        self,
        scheduling_config: "SchedulingNamespaceConfig | None" = None,
        settings: FlowAlertingRuntimeSettings | None = None,
        environ: Mapping[str, str] | None = None,
        registry: "FlowAlertTransportRegistry | None" = None,
        project_name: str | None = None,
        environment: str | None = None,
    ) -> None:
        super().__init__()
        self._environ: Mapping[str, str] = os.environ if environ is None else environ
        self._environment = environment
        self._project_name = project_name
        self._registry = registry
        self._scheduling_config = scheduling_config
        self._settings = (
            settings
            if settings is not None
            else FlowAlertingRuntimeSettings.from_environment(environ=self._environ)
        )

    @classmethod
    def from_project(
        cls,
        project: "Project | None",
        environ: Mapping[str, str] | None = None,
    ) -> "FlowAlertingProvider":
        """The provider of a loaded project, or an inert one without a project."""
        env: Mapping[str, str] = os.environ if environ is None else environ
        if project is None:
            return cls(environ=env)
        return cls(
            scheduling_config=project.scheduling_namespace_config,
            environ=env,
            project_name=project.name,
            environment=cls._resolve_environment(
                project=project,
                environ=env,
            ),
        )

    @staticmethod
    def _resolve_environment(
        project: "Project",
        environ: Mapping[str, str],
    ) -> str | None:
        """The environment name, as handed over or as declared, if any.

        A project that declares no environment is a valid place to run a
        flow from, so the declaration's own error is the one swallowed.
        """
        from nld.project.environment_config import NLD_ENVIRONMENT_ENV_VAR
        from nld.project.project_exceptions import NldEnvironmentError

        handed_over = environ.get(NLD_ENVIRONMENT_ENV_VAR)
        if handed_over:
            return handed_over
        try:
            return project.environments.resolve_name()
        except NldEnvironmentError:
            return None

    @property
    def settings(self) -> FlowAlertingRuntimeSettings:
        """The runtime side handed over by the scheduler."""
        return self._settings

    @property
    def registry(self) -> "FlowAlertTransportRegistry":
        """The transports available to this process."""
        return (
            self._registry
            if self._registry is not None
            else get_flow_alert_transport_registry()
        )

    def resolve_config(self, flow_namespace: str) -> "AlertingConfig | None":
        """The declaration in force for a flow's namespace, if any.

        Resolved through ``SchedulingPolicy`` — the one place that knows the
        precedence — so a flow and its scheduled task read the same
        ``alert_on`` and transports.
        """
        if self._scheduling_config is None:
            return None
        from nld.scheduling.services.policy import SchedulingPolicy

        return SchedulingPolicy(self._scheduling_config).alerting_for_namespace(
            namespace=flow_namespace,
        )

    def build_transports(
        self,
        config: "AlertingConfig",
    ) -> list[FlowAlertTransport]:
        """Instantiate the declared transports this environment configures.

        A declared transport whose secrets are not in the environment is
        skipped with a log line, never an error: an undeployed secret
        disables the transport, it does not fail the run. Names were
        validated when the project loaded; settings of a transport that
        could only be imported now are validated here, and a bad block is
        logged and skipped the same way.
        """
        transports: list[FlowAlertTransport] = []
        for name in config.transports:
            transport_class = self.registry.get(name=name)
            try:
                transport = transport_class.from_environment(
                    settings=config.settings_for(transport_name=name),
                    environ=self._environ,
                )
            except ValueError as ex:
                self.log_warn(f"Alert transport '{name}' is misconfigured: {ex}")
                continue
            if transport is None:
                missing = transport_class.missing_env_vars(environ=self._environ)
                self.log_info(
                    f"Alert transport '{name}' is declared but not configured "
                    f"here (missing {missing}): it will not alert"
                )
                continue
            transports.append(transport)
        return transports

    def for_flow(self, flow_namespace: str) -> FlowAlertingService:
        """The alerting service in force for one flow."""
        config = self.resolve_config(flow_namespace=flow_namespace)
        transports = (
            self.build_transports(config=config)
            if config is not None and config.enabled
            else []
        )
        return FlowAlertingService(
            config=config,
            settings=self._settings,
            transports=transports,
            project_name=self._project_name,
            environment=self._environment,
        )
