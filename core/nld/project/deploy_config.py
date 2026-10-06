from nld.pydantic import NldBaseModel


class DeployNamespaceMapping(NldBaseModel):
    """Deploy settings of one declared namespace.

    ``unit`` allows the namespace to be deployed on its own
    (``--namespace``); ``group`` names the deploy group the namespace
    belongs to, the namespaces sharing a group being always deployed
    together. A group member can be deployed on its own as well, which
    deploys its whole group.
    """

    group: str | None = None
    unit: bool = False

    @property
    def is_deployable(self) -> bool:
        """Whether the namespace may be deployed on its own."""
        return self.unit or self.group is not None


class DeployNamespaceConfig(NldBaseModel):
    """Namespace-scoped deploy settings of a project.

    Declared under the ``namespaces`` block of ``nld_project.yml``, one
    ``deploy`` entry per namespace. Unlike the other facets, a deploy
    setting applies to the namespace that declares it, never to its
    descendants through a nearest-ancestor resolution: deploying a
    namespace on its own is opt-in, namespace by namespace, and a group
    joins concrete namespaces (see ``resolve_namespace_deploy_scope``).

    Example YAML:
        namespaces:
          marketing:
            deploy:
              unit: true
          apec:
            deploy:
              group: job_boards
          hellowork:
            deploy:
              group: job_boards
    """

    mappings: dict[str, DeployNamespaceMapping] = {}

    def get_groups(self) -> dict[str, list[str]]:
        """Return the sorted members of every deploy group, by group name."""
        groups: dict[str, list[str]] = {}
        for namespace, mapping in self.mappings.items():
            if mapping.group is None:
                continue
            groups.setdefault(
                mapping.group,
                [],
            ).append(namespace)
        return {group: sorted(members) for group, members in sorted(groups.items())}

    def get_deployable_namespaces(self) -> list[str]:
        """Return the namespaces that may be deployed on their own, sorted."""
        return sorted(
            namespace
            for namespace, mapping in self.mappings.items()
            if mapping.is_deployable
        )

    def is_deployable(self, namespace: str) -> bool:
        """Whether a namespace may be deployed on its own."""
        mapping = self.mappings.get(namespace)
        return mapping is not None and mapping.is_deployable

    def find_group(self, namespace: str) -> str | None:
        """Return the deploy group a declared namespace belongs to, if any."""
        mapping = self.mappings.get(namespace)
        if mapping is None:
            return None
        return mapping.group
