import os
import shutil
from importlib import resources

from nld.docs.models import (
    ISSUE_KIND_BROKEN_REFERENCE,
    ISSUE_KIND_EXTERNAL_REFERENCE,
    SNAPSHOT_SCHEMA_VERSION,
    STATE_SOURCE_NONE,
    DocsSiteConfig,
    DocsSiteProject,
    ProjectSnapshot,
)
from nld.docs.site.site_builder import ASSET_PACKAGE, DocsSiteBuilder
from nld.docs.snapshot_builder import ProjectSnapshotBuilder
from nld.project.project_catalog import NldProjectCatalog
from nld.pydantic import NldBaseModel
from nld.task.context import NldExecutionContext, TaskRequest
from nld.task.context.variables import ROOT_FOLDER_PATH

CATALOG_INDEX_FILE_NAME: str = "index.html"

INDEX_ASSET_FILE_NAMES: tuple[str, ...] = (
    "styles.css",
    "nld_mark.svg",
)


class CatalogProjectBuild(NldBaseModel):
    """One catalogued project, and where its site was written."""

    name: str
    path: str
    folder: str
    structures: int = 0
    flows: int = 0
    predecessors: list[str] = []


class CatalogProjectFailure(NldBaseModel):
    """One catalogued project that could not be documented."""

    name: str
    path: str
    error: str


def resolve_entry_path(
    catalog: NldProjectCatalog,
    catalog_folder_path: str,
    entry_path: str,
) -> str:
    """Resolve a catalogued project's path against the catalog file."""
    base = os.path.normpath(catalog_folder_path)
    if catalog.projects_base_path:
        base = os.path.join(base, catalog.projects_base_path)
    return os.path.abspath(os.path.join(base, entry_path))


def build_project_snapshot(
    project_root_folder_path: str,
    environment: str | None = None,
    external_structures: dict[str, str] | None = None,
) -> ProjectSnapshot:
    """Build one project's snapshot in its own execution context.

    Each catalogued project is a separate nld project with its own
    configuration, connections and entity tree, so it gets its own context
    rather than being loaded into the caller's.
    """
    task_request = TaskRequest(
        execution_name="docs catalog build",
        params={ROOT_FOLDER_PATH: project_root_folder_path},
    )
    context = NldExecutionContext(
        task_request=task_request,
        with_project=True,
    )
    with context:
        context.load_entities()
        return ProjectSnapshotBuilder(
            execution_context=context,
            environment=environment,
            external_structures=external_structures,
        ).build()


def reconcile_external_references(
    snapshot: ProjectSnapshot,
    owners: dict[str, str],
    project_name: str,
) -> None:
    """Re-read a project's unresolved references knowing the platform.

    A reference another catalogued project declares is external and
    expected - a refined layer reading its acquisition layer is the
    normal shape of a platform - so it stops being an error and the node
    stops being drawn as undeclared. One nobody declares stays broken.
    """
    external = {
        structure_id: owner
        for structure_id, owner in owners.items()
        if owner != project_name
    }
    if not external:
        return

    for issue in snapshot.issues:
        if issue.kind != ISSUE_KIND_BROKEN_REFERENCE or issue.reference is None:
            continue
        owner = external.get(issue.reference)
        if owner is None:
            continue
        issue.kind = ISSUE_KIND_EXTERNAL_REFERENCE
        issue.message = issue.message.replace(
            ", which does not exist",
            f", declared by project '{owner}'",
        )

    for node in snapshot.lineage.nodes:
        owner = external.get(node.node_id)
        if owner is None or not node.missing:
            continue
        node.missing = False
        node.external = True
        node.external_project = owner


def collect_catalog_structure_owners(
    catalog_folder_path: str,
    environment: str | None = None,
    exclude_root: str | None = None,
) -> dict[str, str]:
    """Map every structure of a catalog to the project declaring it.

    ``exclude_root`` drops the project being documented, so its own
    structures are never mistaken for someone else's.
    """
    catalog = NldProjectCatalog.from_yaml(root_path=catalog_folder_path)
    excluded = os.path.abspath(exclude_root) if exclude_root else None
    owners: dict[str, str] = {}
    for name in catalog.entry_names:
        entry = catalog.get_entry(name)
        if entry is None:
            continue
        project_root = resolve_entry_path(
            catalog=catalog,
            catalog_folder_path=catalog_folder_path,
            entry_path=entry.path,
        )
        if excluded is not None and project_root == excluded:
            continue
        try:
            snapshot = build_project_snapshot(
                project_root_folder_path=project_root,
                environment=environment,
            )
        except Exception:  # noqa: BLE001 - an unloadable project contributes none
            continue
        for structure in snapshot.structures:
            owners.setdefault(structure.node_id, name)
    return owners


class CatalogSiteBuilder:
    """Builds one site per catalogued project, under a shared root.

    A platform is several nld projects, and a reader should not have to know
    which one holds the table they are looking for. Every project keeps its
    own self-contained site in a subfolder - so a project can still be built
    and read on its own - and a generated index links them together with the
    dependency order the catalog already declares.
    """

    def __init__(
        self,
        catalog: NldProjectCatalog,
        catalog_folder_path: str,
        target_folder_path: str,
        environment: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.catalog = catalog
        self.catalog_folder_path = catalog_folder_path
        self.target_folder_path = target_folder_path
        self.environment = environment
        self.base_url = base_url
        self.failures: list[CatalogProjectFailure] = []

    def build(self) -> list[CatalogProjectBuild]:
        """Build every catalogued project, and the index linking them.

        A project that cannot be loaded - most often because an entity
        model it declares lives in a package this environment does not
        have - is recorded and skipped. One unbuildable product must not
        cost the platform its documentation.
        """
        os.makedirs(self.target_folder_path, exist_ok=True)
        builds: list[CatalogProjectBuild] = []
        self.failures = []

        # Every project is built exactly once. Building one twice would
        # re-register the custom quality rules and incremental types it
        # declares into a process-global registry, and the second
        # registration is refused - so cross-project references are
        # reconciled afterwards, from the snapshots already in hand,
        # rather than by a second pass.
        snapshots: dict[str, ProjectSnapshot] = {}

        for name in self.catalog.entry_names:
            entry = self.catalog.get_entry(name)
            if entry is None:
                continue
            project_root = resolve_entry_path(
                catalog=self.catalog,
                catalog_folder_path=self.catalog_folder_path,
                entry_path=entry.path,
            )
            try:
                snapshot = build_project_snapshot(
                    project_root_folder_path=project_root,
                    environment=self.environment,
                )
            except Exception as error:  # noqa: BLE001 - one project must not stop all
                self.failures.append(
                    CatalogProjectFailure(
                        name=name,
                        path=project_root,
                        error=f"{type(error).__name__}: {error}",
                    )
                )
                continue
            snapshots[name] = snapshot
            builds.append(
                CatalogProjectBuild(
                    name=name,
                    path=project_root,
                    folder=_folder_name(name=name),
                    structures=len(snapshot.structures),
                    flows=len(snapshot.flows),
                    predecessors=self.catalog.predecessors_of(name),
                )
            )

        owners: dict[str, str] = {}
        for name, snapshot in snapshots.items():
            for structure in snapshot.structures:
                owners.setdefault(structure.node_id, name)

        for build in builds:
            snapshot = snapshots[build.name]
            reconcile_external_references(
                snapshot=snapshot,
                owners=owners,
                project_name=build.name,
            )
            folder = build.folder
            DocsSiteBuilder(
                target_folder_path=os.path.join(self.target_folder_path, folder),
            ).build(
                snapshot=snapshot,
                config=DocsSiteConfig(
                    base_url=self.base_url or ".",
                    state_source=STATE_SOURCE_NONE,
                    project_name=snapshot.project.name,
                ),
            )

        self._rewrite_project_switchers(builds=builds)
        self._write_index(builds=builds, failures=self.failures)
        return builds

    def _rewrite_project_switchers(
        self,
        builds: list[CatalogProjectBuild],
    ) -> None:
        """Give every site the full project list, once all are known.

        The switcher of the first project cannot list the last one until the
        last one is built, so each configuration is rewritten at the end
        rather than every site being built twice.
        """
        for build in builds:
            DocsSiteBuilder(
                target_folder_path=os.path.join(self.target_folder_path, build.folder),
            ).write_config(
                config=DocsSiteConfig(
                    base_url=self.base_url or ".",
                    state_source=STATE_SOURCE_NONE,
                    project_name=build.name,
                    projects=[
                        DocsSiteProject(
                            name=other.name,
                            href=f"../{other.folder}/index.html",
                            structures=other.structures,
                            flows=other.flows,
                        )
                        for other in builds
                    ],
                ),
            )

    def _write_index(
        self,
        builds: list[CatalogProjectBuild],
        failures: list[CatalogProjectFailure],
    ) -> str:
        """Write the landing page listing every catalogued project."""
        self._copy_shared_assets()
        path = os.path.join(self.target_folder_path, CATALOG_INDEX_FILE_NAME)
        with open(path, "w", encoding="utf-8") as file_handle:
            file_handle.write(_render_index(builds=builds, failures=failures))
        return path

    def _copy_shared_assets(self) -> None:
        """Put the stylesheet and the mark beside the landing page.

        The index lives above the project folders, so it cannot borrow
        their copies without a path that breaks when the site is served
        from a subdirectory.
        """
        for file_name in INDEX_ASSET_FILE_NAMES:
            source = resources.files(ASSET_PACKAGE).joinpath(file_name)
            destination = os.path.join(self.target_folder_path, file_name)
            with resources.as_file(source) as source_path:
                shutil.copyfile(source_path, destination)


def _folder_name(name: str) -> str:
    """Return a filesystem-safe folder name for a project."""
    return "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in name
    )


def _escape(value: str) -> str:
    """Escape a value for inclusion in the generated index."""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_index(
    builds: list[CatalogProjectBuild],
    failures: list[CatalogProjectFailure] | None = None,
) -> str:
    """Render the catalog landing page, in the palette of the sites it lists."""
    rows = "".join(
        '<tr><td><a href="./'
        + _escape(build.folder)
        + '/index.html">'
        + _escape(build.name)
        + "</a></td><td>"
        + str(build.structures)
        + "</td><td>"
        + str(build.flows)
        + "</td><td>"
        + _escape(", ".join(build.predecessors) or "—")
        + "</td></tr>"
        for build in builds
    )
    total_structures = sum(build.structures for build in builds)
    total_flows = sum(build.flows for build in builds)
    failure_rows = "".join(
        "<tr><td>"
        + _escape(failure.name)
        + "</td><td><code class='inline'>"
        + _escape(failure.error)
        + "</code></td></tr>"
        for failure in (failures or [])
    )
    failure_section = (
        '<section class="card"><h2>Not documented</h2>'
        '<p class="muted">These catalogued projects could not be loaded in '
        "the environment that built this site, most often because an entity "
        "model they declare lives in a package it does not have.</p>"
        "<table><thead><tr><th>Project</th><th>Reason</th></tr></thead>"
        "<tbody>" + failure_rows + "</tbody></table></section>"
        if failure_rows
        else ""
    )
    return f"""<!doctype html>
<html lang="en" data-theme="light">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>nld docs</title>
    <link rel="icon" type="image/svg+xml" href="./nld_mark.svg" />
    <link rel="stylesheet" href="./styles.css" />
  </head>
  <body>
    <div id="app">
      <main id="main">
        <div id="content">
          <a class="brand" href="./index.html"
            ><img class="brand-logo" src="./nld_mark.svg" alt="nld docs"
          /></a>
          <h1>Platform documentation</h1>
          <p class="page-subtitle">
            {len(builds)} project(s), {total_structures} structure(s),
            {total_flows} flow(s). Every project keeps its own site; the
            dependency column is the order the catalog declares.
          </p>
          <section class="card">
            <table>
              <thead>
                <tr>
                  <th>Project</th>
                  <th>Structures</th>
                  <th>Flows</th>
                  <th>Depends on</th>
                </tr>
              </thead>
              <tbody>{rows}</tbody>
            </table>
          </section>
          {failure_section}
        </div>
      </main>
    </div>
  </body>
</html>
"""


__all__ = [
    "CATALOG_INDEX_FILE_NAME",
    "CatalogProjectBuild",
    "CatalogSiteBuilder",
    "SNAPSHOT_SCHEMA_VERSION",
    "build_project_snapshot",
    "resolve_entry_path",
]
