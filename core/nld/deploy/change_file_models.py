from typing import Annotated, Literal

from pydantic import Field, model_validator

from nld.pydantic.base_model import NldBaseModel


class RenameFieldDirective(NldBaseModel):
    """Declared rename of a field on a structure."""

    structure: str
    from_name: str = Field(alias="from")
    to: str


class RenameStructureDirective(NldBaseModel):
    """Declared rename of a structure asset (and its physical table)."""

    from_name: str = Field(alias="from")
    to: str


class RenameFlowDirective(NldBaseModel):
    """Declared rename of a flow asset.

    The physical table name derives from the flow name, so renaming
    a flow also renames its target table.
    """

    from_name: str = Field(alias="from")
    to: str


class BackfillDefaultDirective(NldBaseModel):
    """One-shot default fill of a column for existing rows.

    Structure-scoped: it fills an existing column's NULL values on
    the named structure's physical table. It has nothing to do with
    flow execution/scheduling — contrast with ``ReloadDirective``,
    which is genuinely flow-scoped.
    """

    structure: str
    field: str
    value: str


class ReloadDirective(NldBaseModel):
    """Forced reload of a flow, recorded as a planned state."""

    flow: str
    mode: str = "full"


class ChangeDirective(NldBaseModel):
    """One resolved directive of a deployment change file.

    Exactly one of the directive attributes must be set. Built from
    the grouped ``changes`` declaration by
    ``DeploymentChangeFile.get_directives``, with the target injected
    from the group key.
    """

    backfill_default: BackfillDefaultDirective | None = None
    reload: ReloadDirective | None = None
    rename_field: RenameFieldDirective | None = None
    rename_flow: RenameFlowDirective | None = None
    rename_structure: RenameStructureDirective | None = None

    @model_validator(mode="after")
    def _validate_exactly_one(self) -> "ChangeDirective":
        """Enforce that the directive carries exactly one instruction."""
        set_directives = [
            name
            for name in (
                "backfill_default",
                "reload",
                "rename_field",
                "rename_flow",
                "rename_structure",
            )
            if getattr(self, name) is not None
        ]
        if len(set_directives) != 1:
            raise ValueError(
                "A change directive must set exactly one instruction, "
                f"got: {set_directives or 'none'}",
            )
        return self


class StructureBackfillDefaultChange(NldBaseModel):
    """backfill_default entry of a structure's change list."""

    directive: Literal["backfill_default"]
    field: str
    value: str

    def to_change_directive(self, structure_name: str) -> ChangeDirective:
        """Resolve into a backfill_default directive on the keyed structure."""
        return ChangeDirective(
            backfill_default=BackfillDefaultDirective(
                structure=structure_name,
                field=self.field,
                value=self.value,
            ),
        )


class StructureRenameChange(NldBaseModel):
    """rename_structure entry — the group key is the pre-rename name."""

    directive: Literal["rename_structure"]
    to: str

    def to_change_directive(self, structure_name: str) -> ChangeDirective:
        """Resolve into a rename_structure directive from the keyed name."""
        return ChangeDirective(
            rename_structure=RenameStructureDirective(
                **{"from": structure_name},
                to=self.to,
            ),
        )


class StructureRenameFieldChange(NldBaseModel):
    """rename_field entry of a structure's change list."""

    directive: Literal["rename_field"]
    from_name: str = Field(alias="from")
    to: str

    def to_change_directive(self, structure_name: str) -> ChangeDirective:
        """Resolve into a rename_field directive on the keyed structure."""
        return ChangeDirective(
            rename_field=RenameFieldDirective(
                structure=structure_name,
                **{"from": self.from_name},
                to=self.to,
            ),
        )


StructureChange = Annotated[
    StructureBackfillDefaultChange | StructureRenameChange | StructureRenameFieldChange,
    Field(discriminator="directive"),
]


class FlowReloadChange(NldBaseModel):
    """reload entry of a flow's change list."""

    directive: Literal["reload"]
    mode: str = "full"

    def to_change_directive(self, flow_name: str) -> ChangeDirective:
        """Resolve into a reload directive on the keyed flow."""
        return ChangeDirective(
            reload=ReloadDirective(
                flow=flow_name,
                mode=self.mode,
            ),
        )


class FlowRenameChange(NldBaseModel):
    """rename_flow entry — the group key is the pre-rename name."""

    directive: Literal["rename_flow"]
    to: str

    def to_change_directive(self, flow_name: str) -> ChangeDirective:
        """Resolve into a rename_flow directive from the keyed name."""
        return ChangeDirective(
            rename_flow=RenameFlowDirective(
                **{"from": flow_name},
                to=self.to,
            ),
        )


FlowChange = Annotated[
    FlowRenameChange | FlowReloadChange,
    Field(discriminator="directive"),
]


class DeploymentChanges(NldBaseModel):
    """Change directives grouped by the asset they target.

    Structure-scoped directives are keyed by structure full name and
    flow-scoped directives by flow name; a rename is keyed by the
    name prior to the renaming.
    """

    flows: dict[str, list[FlowChange]] = {}
    structures: dict[str, list[StructureChange]] = {}


class DeploymentChangeFile(NldBaseModel):
    """Authored transition intent, applied exactly once per target.

    Lives in ``.deployments/<change_id>.yaml`` at the project root.
    The ``change_id`` doubles as the file name and the chronological
    ordering key (``<date>_<time>[_<slug>]``).
    """

    change_id: str
    changes: DeploymentChanges

    def get_directives(self) -> list[ChangeDirective]:
        """Flatten the grouped changes into resolved directives.

        Structure-scoped directives come first, then flow-scoped
        ones, each in declaration order with the target injected
        from its group key.
        """
        directives: list[ChangeDirective] = []
        for structure_name, structure_changes in self.changes.structures.items():
            for structure_change in structure_changes:
                directives.append(
                    structure_change.to_change_directive(structure_name),
                )
        for flow_name, flow_changes in self.changes.flows.items():
            for flow_change in flow_changes:
                directives.append(flow_change.to_change_directive(flow_name))
        return directives


class AppliedChangeDirectives(NldBaseModel):
    """The directives of a change file applied so far on a target.

    A change file can be applied over several deploys, each resolving the
    directives of its own scope: ``outcomes`` holds the outcome of every
    directive already resolved, by outcome key, and ``content_hash`` the
    file content they were resolved from.
    """

    content_hash: str
    outcomes: dict[str, str] = {}


class PendingChangeFile(NldBaseModel):
    """A parsed change file not yet in the target's applied-log.

    ``applied_directive_outcomes`` holds the directives an earlier deploy
    already resolved, and ``out_of_scope_directive_keys`` the directives
    outside the current deploy scope: neither is applied by this deploy.
    """

    change_file: DeploymentChangeFile
    content_hash: str
    file_path: str
    applied_directive_outcomes: dict[str, str] = {}
    out_of_scope_directive_keys: list[str] = []

    @property
    def change_id(self) -> str:
        return self.change_file.change_id

    def get_directives_to_apply(self) -> list[ChangeDirective]:
        """Return the directives this deploy applies, in declaration order."""
        return [
            directive
            for directive in self.change_file.get_directives()
            if directive_outcome_key(directive=directive)
            not in self.applied_directive_outcomes
            and directive_outcome_key(directive=directive)
            not in self.out_of_scope_directive_keys
        ]

    def get_unapplied_directives(self) -> list[ChangeDirective]:
        """Return the directives no deploy has resolved yet, whatever the scope."""
        return [
            directive
            for directive in self.change_file.get_directives()
            if directive_outcome_key(directive=directive)
            not in self.applied_directive_outcomes
        ]


def rename_field_outcome_key(directive: RenameFieldDirective) -> str:
    """Canonical outcome key of a rename_field directive."""
    return (
        f"rename_field {directive.structure}: {directive.from_name} -> {directive.to}"
    )


def rename_structure_outcome_key(directive: RenameStructureDirective) -> str:
    """Canonical outcome key of a rename_structure directive."""
    return f"rename_structure {directive.from_name} -> {directive.to}"


def rename_flow_outcome_key(directive: RenameFlowDirective) -> str:
    """Canonical outcome key of a rename_flow directive."""
    return f"rename_flow {directive.from_name} -> {directive.to}"


def backfill_default_outcome_key(directive: BackfillDefaultDirective) -> str:
    """Canonical outcome key of a backfill_default directive."""
    return f"backfill_default {directive.structure}.{directive.field}"


def reload_outcome_key(directive: ReloadDirective) -> str:
    """Canonical outcome key of a reload directive."""
    return f"reload {directive.flow}: {directive.mode}"


def directive_outcome_key(directive: ChangeDirective) -> str:
    """Canonical outcome key of any directive.

    Executors record resolved directives under these keys; a change
    file is applied once every one of its directives has an outcome.
    """
    if directive.rename_field is not None:
        return rename_field_outcome_key(directive=directive.rename_field)
    if directive.rename_structure is not None:
        return rename_structure_outcome_key(directive=directive.rename_structure)
    if directive.rename_flow is not None:
        return rename_flow_outcome_key(directive=directive.rename_flow)
    if directive.backfill_default is not None:
        return backfill_default_outcome_key(directive=directive.backfill_default)
    if directive.reload is not None:
        return reload_outcome_key(directive=directive.reload)
    raise ValueError("Empty change directive has no outcome key.")


def directive_subject_key(directive: ChangeDirective) -> str:
    """Return the key of the asset a directive is resolved on.

    The subject decides whether a directive belongs to a deploy scope:
    the structure a field or default belongs to, the flow reloaded, and
    the new name of a rename, which is the asset that deploys it.
    """
    if directive.rename_field is not None:
        return directive.rename_field.structure
    if directive.rename_structure is not None:
        return directive.rename_structure.to
    if directive.rename_flow is not None:
        return directive.rename_flow.to
    if directive.backfill_default is not None:
        return directive.backfill_default.structure
    if directive.reload is not None:
        return directive.reload.flow
    raise ValueError("Empty change directive has no subject.")


def directive_asset_keys(directive: ChangeDirective) -> set[str]:
    """Return every asset a directive touches, prefixed by its asset type.

    Two directives touching a common asset must apply in change_id order,
    while directives on unrelated assets are independent: this is what
    lets each namespace deploy apply its own directives. A rename touches
    both its old and its new name.
    """
    if directive.rename_field is not None:
        return {f"structure:{directive.rename_field.structure}"}
    if directive.rename_structure is not None:
        return {
            f"structure:{directive.rename_structure.from_name}",
            f"structure:{directive.rename_structure.to}",
        }
    if directive.rename_flow is not None:
        return {
            f"flow:{directive.rename_flow.from_name}",
            f"flow:{directive.rename_flow.to}",
        }
    if directive.backfill_default is not None:
        return {f"structure:{directive.backfill_default.structure}"}
    if directive.reload is not None:
        return {f"flow:{directive.reload.flow}"}
    raise ValueError("Empty change directive has no asset.")
