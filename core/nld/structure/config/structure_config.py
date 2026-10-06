from nld.pydantic import NamespaceMappingConfig, NldBaseModel


class StructureNamespaceMapping(NldBaseModel):
    """Maps a namespace to a database connection and schema."""

    default_connection_name: str
    database_name: str
    schema_name: str
    tags: list[str] = []


class StructureNamespaceConfig(NamespaceMappingConfig[StructureNamespaceMapping]):
    """Namespace-scoped structure settings of a project.

    Each mapping associates an entity namespace (e.g. "source.raw") with the
    database connection and schema where those structures should be deployed.

    Declared under the ``namespaces`` block of ``nld_project.yml``, one
    ``structure`` entry per namespace. See ``NamespaceMappingConfig`` for how a
    namespace resolves to its nearest mapping.

    Example YAML:
        namespaces:
          source.raw:
            structure:
              default_connection_name: pg_main
              database_name: main_db
              schema_name: raw
    """

    def get_mapping(self, namespace: str) -> StructureNamespaceMapping:
        """Return the mapping for a namespace, raising when none applies.

        Structures cannot be deployed or queried without a target, so an
        unmapped namespace is an error rather than a silent default.
        """
        mapping = self.find_mapping(namespace=namespace)
        if mapping is None:
            raise ValueError(f"Namespace '{namespace}' not found in structure config")
        return mapping
