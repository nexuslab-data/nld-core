from collections.abc import Iterable

from pydantic import Field

from nld.deploy.change_file_models import ChangeDirective, directive_subject_key
from nld.exceptions import NldRuntimeException
from nld.project import DeployNamespaceConfig
from nld.pydantic import NldBaseModel, NldNamespace
from nld.structure.config import StructureNamespaceConfig


class NamespaceDeployScopeError(NldRuntimeException):
    """Raised when a namespace deploy would write outside its scope."""


class NamespaceDeployNotEnabledError(NamespaceDeployScopeError):
    """Raised when a namespace is deployed on its own without being declared so."""


class DeployTarget(NldBaseModel):
    """The connection, database and schema a namespace deploys to."""

    connection_name: str
    database_name: str
    schema_name: str

    @property
    def lock_key(self) -> str:
        """Key of the deploy lock guarding this target.

        The database is left out: deploy addresses a target through its
        connection and schema only, so two mappings differing by their
        database name alone still share one physical schema.
        """
        return f"{self.connection_name}:{self.schema_name}"

    def __str__(self) -> str:
        return f"{self.connection_name}:{self.database_name}.{self.schema_name}"


def resolve_deploy_target(
    structure_namespace_config: StructureNamespaceConfig,
    namespace: str,
) -> DeployTarget | None:
    """Return the deploy target a namespace resolves to, None when unmapped."""
    mapping = structure_namespace_config.find_mapping(namespace=namespace)
    if mapping is None:
        return None
    return DeployTarget(
        connection_name=mapping.default_connection_name,
        database_name=mapping.database_name,
        schema_name=mapping.schema_name,
    )


class NamespaceDeployScope(NldBaseModel):
    """The namespaces a namespace-scoped deploy may read and write.

    A deployment unit is a namespace together with every descendant that
    resolves to the same deploy target: a descendant mapped to another
    schema is a unit of its own and stays out. The scope is the union of
    the units rooted at ``unit_namespaces`` — the requested namespace,
    widened to every member of the deploy groups it overlaps.

    Membership is decided by the namespace configuration alone, never by
    the entities on disk, so it also answers for the namespace of a
    deployed asset that no longer exists in the project.
    """

    groups: list[str] = []
    requested_namespace: str
    structure_namespace_config: StructureNamespaceConfig = Field(exclude=True)
    unit_namespaces: list[str]

    def contains(self, namespace: str) -> bool:
        """Whether a namespace belongs to one of the units in scope."""
        return any(
            self._unit_contains(
                unit_namespace=unit_namespace,
                namespace=namespace,
            )
            for unit_namespace in self.unit_namespaces
        )

    def contains_entity_key(self, entity_key: str) -> bool:
        """Whether an entity key such as ``sales.raw_order`` belongs to the scope."""
        namespace, _, _ = entity_key.rpartition(".")
        return self.contains(namespace=namespace or NldNamespace.ROOT_VALUE)

    def contains_directive(self, directive: ChangeDirective) -> bool:
        """Whether a change directive belongs to the scope, by its subject asset."""
        return self.contains_entity_key(
            entity_key=directive_subject_key(directive=directive),
        )

    def find_excluded_namespaces(self, namespaces: Iterable[str]) -> list[str]:
        """Return the namespaces below a unit root that are out of scope.

        These are the descendants mapped to another deploy target: they
        would have been deployed by the namespace subtree, so a deploy
        names them to make their exclusion visible. Only the topmost
        excluded namespaces are returned, their own descendants being
        implied.
        """
        excluded = {
            str(namespace)
            for namespace in namespaces
            if not self.contains(namespace=namespace)
            and any(
                NldNamespace(unit_namespace).contains(namespace)
                for unit_namespace in self.unit_namespaces
            )
        }
        return sorted(
            namespace
            for namespace in excluded
            if not any(
                other != namespace and NldNamespace(other).contains(namespace)
                for other in excluded
            )
        )

    def get_targets(self) -> list[DeployTarget]:
        """Return the deploy targets of the units in scope, unmapped ones left out."""
        targets: dict[str, DeployTarget] = {}
        for unit_namespace in self.unit_namespaces:
            target = self._target_of(namespace=unit_namespace)
            if target is not None:
                targets[str(target)] = target
        return [targets[key] for key in sorted(targets)]

    def describe(self) -> str:
        """Describe the scope for logs and error messages.

        Example: ``namespace 'apec' (deploy group job_boards: apec, hellowork)``.
        """
        description = f"namespace '{self.requested_namespace}'"
        if self.groups:
            description += (
                f" (deploy group {', '.join(self.groups)}: "
                f"{', '.join(self.unit_namespaces)})"
            )
        return description

    def _unit_contains(self, unit_namespace: str, namespace: str) -> bool:
        """Whether a namespace belongs to the unit rooted at ``unit_namespace``."""
        if not NldNamespace(unit_namespace).contains(namespace):
            return False
        return self._target_of(namespace=namespace) == self._target_of(
            namespace=unit_namespace,
        )

    def _target_of(self, namespace: str) -> DeployTarget | None:
        return resolve_deploy_target(
            structure_namespace_config=self.structure_namespace_config,
            namespace=namespace,
        )


def resolve_lock_keys(
    deploy_scope: NamespaceDeployScope | None,
    structure_namespace_config: StructureNamespaceConfig,
) -> list[str]:
    """Return the keys of the deploy targets a deploy may change.

    A namespace deploy changes its units' targets only; a full-project
    deploy (no scope) may change every target the project maps a
    namespace to.
    """
    if deploy_scope is not None:
        targets = deploy_scope.get_targets()
    else:
        targets = [
            DeployTarget(
                connection_name=mapping.default_connection_name,
                database_name=mapping.database_name,
                schema_name=mapping.schema_name,
            )
            for mapping in structure_namespace_config.mappings.values()
        ]
    return sorted({target.lock_key for target in targets})


def resolve_namespace_deploy_scope(
    namespace: str,
    structure_namespace_config: StructureNamespaceConfig,
    deploy_namespace_config: DeployNamespaceConfig,
) -> NamespaceDeployScope:
    """Resolve the scope of a deploy requested for one namespace.

    Deploying a namespace on its own is opt-in: the namespace must declare
    ``deploy: {unit: true}`` or a deploy group in ``nld_project.yml``,
    otherwise ``NamespaceDeployNotEnabledError`` is raised before anything
    is read from a target. Only the declared namespace itself qualifies,
    not the namespaces inside it: a single asset is deployed with ``--name``.

    The scope starts as the requested namespace's unit. Every deploy group
    with a member whose unit overlaps the scope then joins it whole, until
    no group is left to add: a group is always deployed together, whether
    the deploy names a member or an ancestor whose unit contains a member.
    """
    _check_namespace_deploy_enabled(
        namespace=str(NldNamespace(namespace)),
        deploy_namespace_config=deploy_namespace_config,
    )
    unit_namespaces: set[str] = {str(NldNamespace(namespace))}
    groups: set[str] = set()
    deploy_groups = deploy_namespace_config.get_groups()

    scope = NamespaceDeployScope(
        requested_namespace=str(NldNamespace(namespace)),
        structure_namespace_config=structure_namespace_config,
        unit_namespaces=sorted(unit_namespaces),
    )
    widened = True
    while widened:
        widened = False
        for group, members in deploy_groups.items():
            if group in groups:
                continue
            if not any(
                _unit_overlaps_scope(
                    scope=scope,
                    unit_namespace=member,
                )
                for member in members
            ):
                continue
            groups.add(group)
            unit_namespaces.update(members)
            scope = scope.model_copy(
                update={"unit_namespaces": sorted(unit_namespaces)},
            )
            widened = True

    return scope.model_copy(
        update={
            "groups": sorted(groups),
            "unit_namespaces": _drop_nested_units(
                scope=scope,
                unit_namespaces=unit_namespaces,
            ),
        },
    )


def _check_namespace_deploy_enabled(
    namespace: str,
    deploy_namespace_config: DeployNamespaceConfig,
) -> None:
    """Refuse a namespace that ``nld_project.yml`` does not declare deployable."""
    if deploy_namespace_config.is_deployable(namespace):
        return
    message = (
        f"Namespace '{namespace}' cannot be deployed on its own: declare "
        f"'deploy: {{unit: true}}' on it in the namespaces block of "
        f"nld_project.yml, or deploy the whole project"
    )
    enclosing = [
        declared
        for declared in deploy_namespace_config.get_deployable_namespaces()
        if declared != namespace and NldNamespace(declared).contains(namespace)
    ]
    if enclosing:
        message += (
            f". It lies inside the deployable namespace '{enclosing[-1]}': "
            f"deploy --namespace {enclosing[-1]}, or one asset with --name"
        )
    else:
        message += ". Deploy one asset with --name"
    raise NamespaceDeployNotEnabledError(message)


def _unit_overlaps_scope(
    scope: NamespaceDeployScope,
    unit_namespace: str,
) -> bool:
    """Whether the unit rooted at ``unit_namespace`` shares a namespace with the scope.

    Two units overlap only when one root contains the other on the same
    target: either the member is inside the scope, or a scope root sits
    inside the member's unit.
    """
    if scope.contains(namespace=unit_namespace):
        return True
    member_scope = scope.model_copy(update={"unit_namespaces": [unit_namespace]})
    return any(
        member_scope.contains(namespace=scope_namespace)
        for scope_namespace in scope.unit_namespaces
    )


def _drop_nested_units(
    scope: NamespaceDeployScope,
    unit_namespaces: set[str],
) -> list[str]:
    """Remove the unit roots already covered by another root's unit."""
    kept: list[str] = []
    for unit_namespace in sorted(unit_namespaces):
        other_scope = scope.model_copy(
            update={
                "unit_namespaces": [
                    other for other in unit_namespaces if other != unit_namespace
                ],
            },
        )
        if not other_scope.contains(namespace=unit_namespace):
            kept.append(unit_namespace)
    return kept
