import glob
import hashlib
import os
import re
from collections.abc import Callable
from typing import Any

from nld.deploy.change_file_models import (
    AppliedChangeDirectives,
    BackfillDefaultDirective,
    ChangeDirective,
    DeploymentChangeFile,
    PendingChangeFile,
    ReloadDirective,
    RenameFieldDirective,
    RenameFlowDirective,
    RenameStructureDirective,
    directive_asset_keys,
    directive_outcome_key,
)
from nld.exceptions import NldRuntimeException
from nld.utils.yaml_util import load_yaml_file_into_dict

DEPLOYMENTS_FOLDER = ".deployments"

CHANGE_ID_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}_\d{4}(_[a-z0-9][a-z0-9-]*)?$",
)


class ChangeFileError(NldRuntimeException):
    """Raised when the deployment change files are inconsistent."""


def get_deployments_folder_path(
    project_root_folder_path: str,
) -> str:
    """Return the path of the change-file folder at the project root."""
    return os.path.join(
        project_root_folder_path,
        DEPLOYMENTS_FOLDER,
    )


def compute_change_file_hash(
    file_path: str,
) -> str:
    """Compute the content hash recorded in the applied-log."""
    with open(file_path, "rb") as file_handle:
        return hashlib.sha256(file_handle.read()).hexdigest().upper()


def load_change_files(
    project_root_folder_path: str,
) -> list[PendingChangeFile]:
    """Load every change file, validated and sorted by change_id.

    Validations: the change_id must follow the
    ``<date>_<time>[_<slug>]`` convention, match the file name, and
    be unique.
    """
    deploy_dir = get_deployments_folder_path(
        project_root_folder_path=project_root_folder_path,
    )
    if not os.path.isdir(deploy_dir):
        return []

    loaded: list[PendingChangeFile] = []
    seen_change_ids: set[str] = set()
    for file_path in sorted(glob.glob(os.path.join(deploy_dir, "*.yaml"))):
        data = load_yaml_file_into_dict(file_path=file_path)
        change_file = DeploymentChangeFile(**data)
        change_id = change_file.change_id

        if not CHANGE_ID_PATTERN.match(change_id):
            raise ChangeFileError(
                f"Change file '{file_path}': change_id '{change_id}' does not "
                "follow the '<date>_<time>[_<slug>]' naming convention "
                "(e.g. 2026-07-02_1430_rename-order-status).",
            )
        file_base_name = os.path.splitext(os.path.basename(file_path))[0]
        if file_base_name != change_id:
            raise ChangeFileError(
                f"Change file '{file_path}': file name '{file_base_name}' "
                f"must equal its change_id '{change_id}'.",
            )
        if change_id in seen_change_ids:
            raise ChangeFileError(
                f"Duplicate change_id '{change_id}' in '{deploy_dir}'.",
            )
        seen_change_ids.add(change_id)

        loaded.append(
            PendingChangeFile(
                change_file=change_file,
                content_hash=compute_change_file_hash(file_path=file_path),
                file_path=file_path,
            ),
        )

    return sorted(loaded, key=lambda change: change.change_id)


def resolve_pending_change_files(
    project_root_folder_path: str,
    applied_hashes_by_change_id: dict[str, str],
    applied_directives_by_change_id: dict[str, AppliedChangeDirectives] | None = None,
) -> list[PendingChangeFile]:
    """Return the pending change files, in chronological order.

    A file is pending until every one of its directives is applied; the
    directives an earlier deploy already resolved are carried on the file
    so that no deploy applies them twice. Enforces the applied-log
    invariants:
    - a change file whose content hash changed after any of its
      directives was applied is an error (change files are immutable
      once applied);
    - an unapplied directive older than an applied directive touching a
      common asset is an error (out-of-order gap), never silently
      skipped. Directives on unrelated assets are independent, so a
      namespace deploy applying its own directives never blocks the
      directives another namespace still has to apply.
    """
    applied_directives_by_change_id = applied_directives_by_change_id or {}
    all_files = load_change_files(
        project_root_folder_path=project_root_folder_path,
    )

    pending: list[PendingChangeFile] = []
    for change in all_files:
        applied_hash = applied_hashes_by_change_id.get(change.change_id)
        if applied_hash is not None:
            _check_content_hash(
                change=change,
                applied_hash=applied_hash,
            )
            _check_out_of_order_gap(
                pending=pending,
                applied_change=change,
                applied_directives=change.change_file.get_directives(),
            )
            continue

        applied_directives = applied_directives_by_change_id.get(change.change_id)
        if applied_directives is not None:
            _check_content_hash(
                change=change,
                applied_hash=applied_directives.content_hash,
            )
            change = change.model_copy(
                update={"applied_directive_outcomes": applied_directives.outcomes},
            )
            if not change.get_unapplied_directives():
                # Every directive is recorded although the file row is
                # missing: the file is applied all the same.
                _check_out_of_order_gap(
                    pending=pending,
                    applied_change=change,
                    applied_directives=change.change_file.get_directives(),
                )
                continue
            _check_out_of_order_gap(
                pending=pending,
                applied_change=change,
                applied_directives=[
                    directive
                    for directive in change.change_file.get_directives()
                    if directive_outcome_key(directive=directive)
                    in applied_directives.outcomes
                ],
            )
        pending.append(change)

    return pending


def _check_content_hash(
    change: PendingChangeFile,
    applied_hash: str,
) -> None:
    """Refuse a change file edited after one of its directives was applied."""
    if applied_hash != change.content_hash:
        raise ChangeFileError(
            f"Change file '{change.change_id}' was modified after being "
            "applied (content hash mismatch). Applied change files are "
            "immutable: declare a new change file instead.",
        )


def _check_out_of_order_gap(
    pending: list[PendingChangeFile],
    applied_change: PendingChangeFile,
    applied_directives: list[ChangeDirective],
) -> None:
    """Refuse older unapplied directives touching an asset a newer one changed.

    ``pending`` holds the files older than ``applied_change``, whose
    ``applied_directives`` are already resolved on the target.
    """
    applied_asset_keys = {
        asset_key
        for directive in applied_directives
        for asset_key in directive_asset_keys(directive=directive)
    }
    gap_change_ids: list[str] = []
    gap_asset_keys: set[str] = set()
    for older_change in pending:
        older_asset_keys = {
            asset_key
            for directive in older_change.get_unapplied_directives()
            for asset_key in directive_asset_keys(directive=directive)
        }
        common_asset_keys = older_asset_keys & applied_asset_keys
        if common_asset_keys:
            gap_change_ids.append(older_change.change_id)
            gap_asset_keys |= common_asset_keys
    if gap_change_ids:
        raise ChangeFileError(
            f"Out-of-order gap: change file(s) [{', '.join(gap_change_ids)}] "
            f"are older than the already-applied '{applied_change.change_id}' "
            f"and touch the same asset(s) [{', '.join(sorted(gap_asset_keys))}] "
            "but were never applied.",
        )


def scope_pending_change_files(
    pending_change_files: list[PendingChangeFile],
    is_directive_in_scope: Callable[[ChangeDirective], bool],
) -> list[PendingChangeFile]:
    """Keep the pending files with directives to apply in the deploy scope.

    The directives outside the scope are marked on the kept files, so the
    grouping helpers below never hand them to the deploy; a file with no
    directive left to apply in scope is dropped, so it neither shows in
    the change set nor counts as a pending change.
    """
    scoped: list[PendingChangeFile] = []
    for change in pending_change_files:
        out_of_scope_directive_keys = [
            directive_outcome_key(directive=directive)
            for directive in change.get_unapplied_directives()
            if not is_directive_in_scope(directive)
        ]
        scoped_change = change.model_copy(
            update={"out_of_scope_directive_keys": out_of_scope_directive_keys},
        )
        if scoped_change.get_directives_to_apply():
            scoped.append(scoped_change)
    return scoped


def group_field_renames_by_structure(
    pending_change_files: list[PendingChangeFile],
) -> dict[str, list[RenameFieldDirective]]:
    """Group the pending rename_field directives by structure full name."""
    grouped: dict[str, list[RenameFieldDirective]] = {}
    for change in pending_change_files:
        for directive in change.get_directives_to_apply():
            if directive.rename_field is None:
                continue
            grouped.setdefault(
                directive.rename_field.structure,
                [],
            ).append(directive.rename_field)
    return grouped


def group_structure_renames_by_target(
    pending_change_files: list[PendingChangeFile],
) -> dict[str, list[RenameStructureDirective]]:
    """Group the pending rename_structure directives by their target name."""
    grouped: dict[str, list[RenameStructureDirective]] = {}
    for change in pending_change_files:
        for directive in change.get_directives_to_apply():
            if directive.rename_structure is None:
                continue
            grouped.setdefault(
                directive.rename_structure.to,
                [],
            ).append(directive.rename_structure)
    return grouped


def group_structure_renames_by_source(
    pending_change_files: list[PendingChangeFile],
) -> dict[str, list[RenameStructureDirective]]:
    """Group the pending rename_structure directives by their source name.

    A structure whose name matches a directive's ``from`` entry sits
    on a name another asset is moving away from: the deploy of that
    structure must wait until the rename target released the name.
    """
    grouped: dict[str, list[RenameStructureDirective]] = {}
    for change in pending_change_files:
        for directive in change.get_directives_to_apply():
            if directive.rename_structure is None:
                continue
            grouped.setdefault(
                directive.rename_structure.from_name,
                [],
            ).append(directive.rename_structure)
    return grouped


def get_flow_renames(
    pending_change_files: list[PendingChangeFile],
) -> list[RenameFlowDirective]:
    """Collect the pending rename_flow directives in chronological order."""
    return [
        directive.rename_flow
        for change in pending_change_files
        for directive in change.get_directives_to_apply()
        if directive.rename_flow is not None
    ]


def group_backfill_defaults_by_structure(
    pending_change_files: list[PendingChangeFile],
) -> dict[str, list[BackfillDefaultDirective]]:
    """Group the pending backfill_default directives by structure full name.

    backfill_default is structure-scoped (a one-shot fill of a
    column's NULL values on the named structure's physical table),
    so it is resolved during structure deploy — grouped the same way
    as the other structure-scoped directives (rename_field,
    rename_structure), not through the flow that happens to produce
    the structure.
    """
    grouped: dict[str, list[BackfillDefaultDirective]] = {}
    for change in pending_change_files:
        for directive in change.get_directives_to_apply():
            if directive.backfill_default is None:
                continue
            grouped.setdefault(
                directive.backfill_default.structure,
                [],
            ).append(directive.backfill_default)
    return grouped


def get_reloads(
    pending_change_files: list[PendingChangeFile],
) -> list[ReloadDirective]:
    """Collect the pending reload directives in chronological order."""
    return [
        directive.reload
        for change in pending_change_files
        for directive in change.get_directives_to_apply()
        if directive.reload is not None
    ]


def validate_backfill_default_targets(
    backfill_defaults_by_structure: dict[str, list[Any]],
    entity_registry: Any,
) -> None:
    """Refuse a backfill_default directive that targets a view.

    A view has no physical column to fill. Views are never part of a
    deploy scope (only TABLE structures deploy), so without this
    upfront check a view target would sit pending forever with no
    diagnostic — this fails loudly at plan/deploy time regardless of
    the current scope.
    """
    for structure_full_name in backfill_defaults_by_structure:
        namespace, _, structure_name = structure_full_name.rpartition(".")
        namespaced_structure = entity_registry.get_structure(
            entity_key=structure_name,
            namespace=namespace or None,
        )
        if namespaced_structure.model.is_view():
            raise ChangeFileError(
                f"backfill_default targets '{structure_full_name}', "
                "which is a VIEW — a view has no physical column to "
                "backfill. backfill_default can only target a TABLE "
                "structure.",
            )
