import os
import subprocess
from typing import Any, ClassVar

from nld.exceptions import NldRuntimeException
from nld.flow.graph.data_flow_graph import (
    FLOW_NODE_TYPE,
    STRUCTURE_NODE_TYPE,
    DataFlowGraph,
    strip_node_type_prefix,
)
from nld.parameters.execution_params_def import ExecutionParameterDefinition
from nld.service import EntityTypeNames
from nld.task.base import StandardTask

ASSET_FILE_EXTENSIONS = (".yml", ".yaml", ".sql", ".py")


class DeployImpactTask(StandardTask):
    """``nld deploy impact`` — repository-only impact analysis (F-6).

    Diffs the repository against a git base, maps the changed files
    to flow and structure assets, and expands the impact through the
    dependency graph. Predecessors are mandatory and explicit in the
    flow YAML, so the downstream expansion is complete without any
    database connection — nothing is read from or written to a
    target.
    """

    init_params: ClassVar[list[str | ExecutionParameterDefinition]] = [
        ExecutionParameterDefinition(
            name="git_base",
            mandatory=True,
        ),
    ]
    run_params: ClassVar[list[str | ExecutionParameterDefinition]] = []

    def __init__(
        self,
        git_base: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._git_base = git_base
        self.execution_context.load_entities(
            entity_types=[EntityTypeNames.DATA_FLOW_DEFINITION],
        )

    def run(self, **kwargs: Any) -> dict[str, Any]:
        """Compute and report the changed and impacted assets."""
        entities_root = self.execution_context.project.entities_root_folder_path
        changed_paths = self._list_changed_paths(
            entities_root=entities_root,
        )

        changed_flows: set[str] = set()
        changed_structures: set[str] = set()
        changed_change_files: list[str] = []
        unmapped_paths: list[str] = []
        for relative_path in changed_paths:
            self._map_path_to_asset(
                relative_path=relative_path,
                changed_flows=changed_flows,
                changed_structures=changed_structures,
                changed_change_files=changed_change_files,
                unmapped_paths=unmapped_paths,
            )

        impacted_flows, impacted_structures = self._expand_impact(
            changed_flows=changed_flows,
            changed_structures=changed_structures,
        )

        data: dict[str, Any] = {
            "git_base": self._git_base,
            "changed_flows": sorted(changed_flows),
            "changed_structures": sorted(changed_structures),
            "changed_change_files": sorted(changed_change_files),
            "impacted_flows": sorted(impacted_flows - changed_flows),
            "impacted_structures": sorted(impacted_structures - changed_structures),
            "unmapped_paths": sorted(unmapped_paths),
        }
        self._report(data=data)
        return data

    def _list_changed_paths(
        self,
        entities_root: str,
    ) -> list[str]:
        """List the changed files relative to the entities root.

        Combines the working tree diff against the git base with the
        untracked files, so uncommitted work is analyzed too.
        """
        git_toplevel = self._run_git(
            arguments=["rev-parse", "--show-toplevel"],
            working_directory=entities_root,
        ).strip()
        diff_output = self._run_git(
            arguments=["diff", "--name-only", self._git_base],
            working_directory=entities_root,
        )
        untracked_output = self._run_git(
            arguments=["ls-files", "--others", "--exclude-standard"],
            working_directory=entities_root,
        )

        entities_prefix = os.path.relpath(
            os.path.abspath(entities_root),
            git_toplevel,
        )
        changed: list[str] = []
        for line in (diff_output + untracked_output).splitlines():
            path = line.strip()
            if not path:
                continue
            if entities_prefix != ".":
                if not path.startswith(f"{entities_prefix}/"):
                    continue
                path = path[len(entities_prefix) + 1 :]
            changed.append(path)
        return sorted(set(changed))

    def _run_git(
        self,
        arguments: list[str],
        working_directory: str,
    ) -> str:
        """Run a git command and return its stdout."""
        result = subprocess.run(
            ["git", *arguments],
            capture_output=True,
            cwd=working_directory,
            text=True,
        )
        if result.returncode != 0:
            raise NldRuntimeException(
                f"git {' '.join(arguments)} failed: {result.stderr.strip()}",
            )
        return result.stdout

    @staticmethod
    def _map_path_to_asset(
        relative_path: str,
        changed_flows: set[str],
        changed_structures: set[str],
        changed_change_files: list[str],
        unmapped_paths: list[str],
    ) -> None:
        """Map one changed file to its asset, by project layout."""
        parts = relative_path.split("/")
        root_folder = parts[0]
        base_name, extension = os.path.splitext(parts[-1])

        if root_folder == ".deployments" and extension in (".yml", ".yaml"):
            changed_change_files.append(base_name)
            return
        if len(parts) < 2 or extension not in ASSET_FILE_EXTENSIONS:
            unmapped_paths.append(relative_path)
            return

        namespace_parts = parts[1:-1]
        full_name = ".".join([*namespace_parts, base_name])
        if root_folder == "flows":
            changed_flows.add(full_name)
        elif root_folder == "structure":
            changed_structures.add(full_name)
        else:
            unmapped_paths.append(relative_path)

    def _expand_impact(
        self,
        changed_flows: set[str],
        changed_structures: set[str],
    ) -> tuple[set[str], set[str]]:
        """Expand the changed assets downstream through the flow graph."""
        registry = self.execution_context.entity_registry
        graph = DataFlowGraph(
            flow_dict=registry.get_data_flow_definition_dict(),
        )

        impacted_flows: set[str] = set()
        impacted_structures: set[str] = set()
        changed_nodes = [(FLOW_NODE_TYPE, name) for name in changed_flows] + [
            (STRUCTURE_NODE_TYPE, name) for name in changed_structures
        ]

        for node_type, full_name in changed_nodes:
            node_id = f"{node_type}.{full_name}"
            if node_id not in graph.digraph:
                continue
            for descendant in self._descendants(
                graph=graph,
                node_id=node_id,
            ):
                descendant_name = strip_node_type_prefix(descendant)
                if descendant.startswith(f"{FLOW_NODE_TYPE}."):
                    impacted_flows.add(descendant_name)
                else:
                    impacted_structures.add(descendant_name)

        return impacted_flows, impacted_structures

    @staticmethod
    def _descendants(
        graph: DataFlowGraph,
        node_id: str,
    ) -> set[str]:
        """Collect the transitive downstream nodes of a graph node."""
        descendants: set[str] = set()
        frontier = [node_id]
        while frontier:
            current = frontier.pop()
            for successor in graph.digraph.successors(current):  # type: ignore[no-untyped-call]
                if successor not in descendants:
                    descendants.add(successor)
                    frontier.append(successor)
        return descendants

    def _report(
        self,
        data: dict[str, Any],
    ) -> None:
        """Log the human-readable impact report."""
        self.log_info(f"Impact analysis against '{data['git_base']}' (repo-only):")
        for label, key in [
            ("Changed flows", "changed_flows"),
            ("Changed structures", "changed_structures"),
            ("Pending change files", "changed_change_files"),
            ("Impacted downstream flows", "impacted_flows"),
            ("Impacted downstream structures", "impacted_structures"),
        ]:
            values = data[key]
            rendered = ", ".join(values) if values else "none"
            self.log_info(f"  {label}: {rendered}")
        if data["unmapped_paths"]:
            self.log_info(
                f"  Changed files outside assets: {', '.join(data['unmapped_paths'])}",
            )
