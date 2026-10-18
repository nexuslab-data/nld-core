import os
import webbrowser
from typing import Any, ClassVar

from nld.docs.catalog import CatalogSiteBuilder, collect_catalog_structure_owners
from nld.docs.models import (
    ISSUE_KIND_UNUSED_TEMPLATE,
    STATE_SOURCE_API,
    STATE_SOURCE_FILE,
    STATE_SOURCE_NONE,
    DocsSiteConfig,
    ProjectSnapshot,
)
from nld.docs.server.docs_server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DocsServer,
    is_loopback_host,
)
from nld.docs.site.site_builder import DocsSiteBuilder
from nld.docs.snapshot_builder import ProjectSnapshotBuilder
from nld.docs.state.cache import DEFAULT_STATE_TTL_SECONDS, CachedStateProvider
from nld.docs.state.collector import LiveStateCollector
from nld.docs.state.models import DocsLiveState
from nld.parameters import ExecutionParameterDefinition
from nld.project.project_catalog import NldProjectCatalog
from nld.task.base import StandardTask

DEFAULT_TARGET_FOLDER_NAME: str = os.path.join("output", "nld-docs")


class AbstractDocsTask(StandardTask):
    """Common wiring of the ``nld docs`` commands.

    Loads every entity type — the documentation covers the whole project, not
    a slice of it — and resolves the target folder the site is written to.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(name="target", mandatory=False),
        ExecutionParameterDefinition(name="environment", mandatory=False),
        ExecutionParameterDefinition(name="base_url", mandatory=False),
        ExecutionParameterDefinition(name="state_url", mandatory=False),
        ExecutionParameterDefinition(name="state_source", mandatory=False),
        ExecutionParameterDefinition(name="catalog", mandatory=False),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        target: str | None = None,
        environment: str | None = None,
        base_url: str | None = None,
        state_url: str | None = None,
        state_source: str | None = None,
        catalog: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.environment = environment
        self.catalog_folder_path = os.path.abspath(catalog) if catalog else None
        self.base_url = base_url
        self.state_url = state_url
        self.state_source = state_source
        self.execution_context.load_entities()
        self.target_folder_path = self._resolve_target_folder_path(target=target)

    def _resolve_target_folder_path(
        self,
        target: str | None,
    ) -> str:
        """Resolve where the site is written, defaulting inside the project."""
        if target is not None:
            return os.path.abspath(target)
        return os.path.join(
            self.execution_context.get_nld_root_folder_path(),
            DEFAULT_TARGET_FOLDER_NAME,
        )

    def build_snapshot(self) -> ProjectSnapshot:
        """Build the project snapshot from the loaded entities.

        Naming a catalog lets a reference into another project of the
        platform be recognised as external rather than broken, which for
        a refined layer reading its acquisition layer is the difference
        between a clean report and a page of false alarms.
        """
        builder = ProjectSnapshotBuilder(
            execution_context=self.execution_context,
            environment=self.environment,
            external_structures=self.external_structures(),
        )
        return builder.build()

    def external_structures(self) -> dict[str, str]:
        """Structures declared by the other projects of the catalog."""
        if self.catalog_folder_path is None:
            return {}
        return collect_catalog_structure_owners(
            catalog_folder_path=self.catalog_folder_path,
            environment=self.environment,
            exclude_root=self.execution_context.get_nld_root_folder_path(),
        )

    def site_config(
        self,
        snapshot: ProjectSnapshot,
        state_source: str,
    ) -> DocsSiteConfig:
        """Describe, for the generated page, where its data lives."""
        return DocsSiteConfig(
            base_url=self.base_url or ".",
            state_source=state_source,
            state_url=self.state_url,
            project_name=snapshot.project.name,
        )

    def resolve_state_source(
        self,
        default: str = STATE_SOURCE_NONE,
    ) -> str:
        """Resolve how the published page should reach its live state.

        An explicit ``--state-source`` wins; otherwise naming a state URL is
        taken as asking for it, which is the only reason to pass one.
        """
        if self.state_source:
            return self.state_source.lower()
        if self.state_url:
            return STATE_SOURCE_FILE
        return default

    def build_site(
        self,
        snapshot: ProjectSnapshot,
        with_launcher: bool = False,
        state_source: str = STATE_SOURCE_NONE,
    ) -> list[str]:
        """Write the site for a snapshot and log where it landed."""
        site_builder = DocsSiteBuilder(
            target_folder_path=self.target_folder_path,
        )
        written = site_builder.build(
            snapshot=snapshot,
            with_launcher=with_launcher,
            config=self.site_config(
                snapshot=snapshot,
                state_source=state_source,
            ),
        )
        self.log_info(f"Documentation site written to {self.target_folder_path}")
        return written

    def log_issues(
        self,
        snapshot: ProjectSnapshot,
    ) -> None:
        """Report the broken references and unused templates the build found."""
        if not snapshot.issues:
            return
        self.log_info("Repository issues:")
        for issue in snapshot.issues:
            level = "info" if issue.kind == ISSUE_KIND_UNUSED_TEMPLATE else "error"
            self.log_info(f"  [{level}] {issue.asset}: {issue.message}")


class DocsBuildTask(AbstractDocsTask):
    """``nld docs build`` — generate the static site from the project assets."""

    def run(self, **kwargs: Any) -> bool:
        """Build the snapshot and write the static site."""
        snapshot = self.build_snapshot()
        self.build_site(
            snapshot=snapshot,
            state_source=self.resolve_state_source(),
        )
        self._log_summary(snapshot=snapshot)
        self.log_issues(snapshot=snapshot)
        return True

    def _log_summary(
        self,
        snapshot: ProjectSnapshot,
    ) -> None:
        """Report what the snapshot holds."""
        coverage = snapshot.documentation_coverage
        self.log_info(
            f"{len(snapshot.structures)} structure(s), "
            f"{len(snapshot.flows)} flow(s), "
            f"{len(snapshot.namespaces)} namespace(s), "
            f"{len(snapshot.lineage.nodes)} lineage node(s)"
        )
        self.log_info(f"Documentation coverage: {coverage.documented}/{coverage.total}")


class DocsDeployTask(AbstractDocsTask):
    """``nld docs deploy`` — produce the self-contained deployable app."""

    def run(self, **kwargs: Any) -> bool:
        """Build the site together with its standalone launcher."""
        snapshot = self.build_snapshot()
        self.build_site(
            snapshot=snapshot,
            with_launcher=True,
            state_source=self.resolve_state_source(),
        )
        self.log_issues(snapshot=snapshot)
        self.log_info(
            f"Run it with: python {os.path.join(self.target_folder_path, 'serve.py')}"
        )
        return True


class DocsServeTask(AbstractDocsTask):
    """``nld docs serve`` — build the site and serve it with the state API."""

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        *AbstractDocsTask.init_params,
        ExecutionParameterDefinition(name="host", mandatory=False),
        ExecutionParameterDefinition(name="port", mandatory=False, data_type="int"),
        ExecutionParameterDefinition(
            name="no_state", mandatory=False, data_type="bool"
        ),
        ExecutionParameterDefinition(
            name="no_build", mandatory=False, data_type="bool"
        ),
        ExecutionParameterDefinition(
            name="open_browser", mandatory=False, data_type="bool"
        ),
        ExecutionParameterDefinition(
            name="state_ttl", mandatory=False, data_type="int"
        ),
    ]

    def __init__(
        self,
        target: str | None = None,
        environment: str | None = None,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        no_state: bool = False,
        no_build: bool = False,
        open_browser: bool = False,
        state_ttl: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            target=target,
            environment=environment,
            **kwargs,
        )
        self.host = host
        self.port = port
        self.no_state = bool(no_state)
        self.no_build = bool(no_build)
        self.open_browser = bool(open_browser)
        self.state_ttl_seconds = (
            float(state_ttl) if state_ttl is not None else DEFAULT_STATE_TTL_SECONDS
        )

    def create_server(self) -> DocsServer:
        """Build the site when asked to and return the configured server."""
        snapshot = self.build_snapshot()
        if not self.no_build:
            self.build_site(
                snapshot=snapshot,
                state_source=(STATE_SOURCE_NONE if self.no_state else STATE_SOURCE_API),
            )

        state_provider = None
        if not self.no_state:

            def collect_state() -> DocsLiveState:
                """Collect the live state when the cache asks for it."""
                collector = LiveStateCollector(
                    execution_context=self.execution_context,
                    snapshot=snapshot,
                    environment=self.environment,
                )
                return collector.collect()

            state_provider = CachedStateProvider(
                collector=collect_state,
                ttl_seconds=self.state_ttl_seconds,
            )

        return DocsServer(
            site_folder_path=self.target_folder_path,
            snapshot=snapshot,
            state_provider=state_provider,
            host=self.host,
            port=self.port,
        )

    def run(self, **kwargs: Any) -> bool:
        """Serve the documentation until the process is interrupted."""
        server = self.create_server()
        server.create()
        self.log_info(f"nld docs available on {server.url}")
        if not is_loopback_host(self.host) and not self.no_state:
            self.log_warn(
                f"Binding to {self.host} exposes the live-state API beyond this "
                f"machine; use --no-state or a loopback address on shared networks."
            )
        self.log_info("Press Ctrl+C to stop.")
        if self.open_browser:
            webbrowser.open(server.url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            self.log_info("Stopped.")
        return True


class DocsStateBuildTask(AbstractDocsTask):
    """``nld docs state build`` — collect the live state into a file.

    A published site has no API to call. This task collects the state once
    and writes it beside the site, so a scheduled job can refresh it while
    the site itself stays static: no endpoint to expose, no credentials in
    a browser, no CORS. The cost is that the state is as fresh as the job.
    """

    def run(self, **kwargs: Any) -> bool:
        """Collect the live state and write it next to the site."""
        snapshot = self.build_snapshot()
        collector = LiveStateCollector(
            execution_context=self.execution_context,
            snapshot=snapshot,
            environment=self.environment,
        )
        state = collector.collect()

        site_builder = DocsSiteBuilder(
            target_folder_path=self.target_folder_path,
        )
        path = site_builder.write_state(state=state)
        config = self.site_config(
            snapshot=snapshot,
            state_source=STATE_SOURCE_FILE,
        )
        config.state_generated_at = state.collected_at
        site_builder.write_config(config=config)

        self.log_info(f"Live state written to {path}")
        if not state.available:
            self.log_warn(
                "No backend could be reached; the published state will show "
                "every section as unavailable."
            )
        return True


class DocsCatalogBuildTask(StandardTask):
    """``nld docs catalog build`` — one site per catalogued project.

    A data platform is several nld projects, and a reader should not have to
    know which one holds the table they are after. Each project keeps its
    own self-contained site, so it can still be built and read alone, and a
    generated index ties them together with the dependency order the
    catalog already declares.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(name="catalog", mandatory=False),
        ExecutionParameterDefinition(name="target", mandatory=False),
        ExecutionParameterDefinition(name="environment", mandatory=False),
        ExecutionParameterDefinition(name="base_url", mandatory=False),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        catalog: str | None = None,
        target: str | None = None,
        environment: str | None = None,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.catalog_folder_path = os.path.abspath(
            catalog or self.execution_context.get_nld_root_folder_path()
        )
        self.environment = environment
        self.base_url = base_url
        self.target_folder_path = (
            os.path.abspath(target)
            if target is not None
            else os.path.join(
                self.execution_context.get_nld_root_folder_path(),
                DEFAULT_TARGET_FOLDER_NAME,
            )
        )

    def run(self, **kwargs: Any) -> bool:
        """Build every catalogued project and the index linking them."""
        catalog = NldProjectCatalog.from_yaml(root_path=self.catalog_folder_path)
        builder = CatalogSiteBuilder(
            catalog=catalog,
            catalog_folder_path=self.catalog_folder_path,
            target_folder_path=self.target_folder_path,
            environment=self.environment,
            base_url=self.base_url,
        )
        builds = builder.build()

        self.log_info(f"Platform documentation written to {self.target_folder_path}")
        self.log_separator_line()
        for build in builds:
            self.log_info(
                f"  {build.name}: {build.structures} structure(s), "
                f"{build.flows} flow(s) -> {build.folder}/"
            )
        self.log_separator_line()
        self.log_info(f"({len(builds)} project(s))")

        if builder.failures:
            self.log_warn(
                f"{len(builder.failures)} project(s) could not be documented:"
            )
            for failure in builder.failures:
                self.log_warn(f"  {failure.name}: {failure.error}")
        return True


class DocsCheckTask(AbstractDocsTask):
    """``nld docs check`` — gate on documentation coverage and broken references.

    Returns ``False`` when a cross-reference points at nothing, and when the
    documented share is under ``--min-coverage``, so CI can fail on either.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        *AbstractDocsTask.init_params,
        ExecutionParameterDefinition(
            name="min_coverage", mandatory=False, data_type="float"
        ),
    ]

    def __init__(
        self,
        target: str | None = None,
        environment: str | None = None,
        min_coverage: float | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            target=target,
            environment=environment,
            **kwargs,
        )
        self.min_coverage = float(min_coverage) if min_coverage is not None else None

    def run(self, **kwargs: Any) -> bool:
        """Report undocumented assets and repository issues, and gate on them."""
        snapshot = self.build_snapshot()
        coverage = snapshot.documentation_coverage

        self.log_info("Documentation coverage:")
        self.log_separator_line()
        self.log_info(
            f"  {coverage.documented} of {coverage.total} documentable asset(s) "
            f"documented ({coverage.ratio:.0%})"
        )
        if coverage.missing:
            self.log_info("  Undocumented assets:")
            for asset in coverage.missing:
                self.log_info(f"    - {asset}")
        self.log_separator_line()
        self.log_issues(snapshot=snapshot)

        passed = True
        broken = snapshot.broken_references
        if broken:
            self.log_error(f"{len(broken)} broken reference(s) found.")
            passed = False
        if self.min_coverage is not None and coverage.ratio < self.min_coverage:
            self.log_error(
                f"Documentation coverage {coverage.ratio:.0%} is under the required "
                f"{self.min_coverage:.0%}."
            )
            passed = False
        return passed
