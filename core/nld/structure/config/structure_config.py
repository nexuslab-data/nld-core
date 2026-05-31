from nld.pydantic import NldBaseModel
from nld.pydantic.namespace import NldNamespace


class StructureProjectMapping(NldBaseModel):
    """Maps a namespace to a database connection and schema."""

    default_connection_name: str
    database_name: str
    schema_name: str
    tags: list[str] = []


class StructureProjectConfig(NldBaseModel):
    """Configuration mapping namespaces to database connections and schemas.

    Each mapping associates an entity namespace (e.g. "source.raw") with the
    database connection and schema where those structures should be deployed.

    When a namespace is not explicitly configured, the lookup walks up the
    hierarchy until a match is found. A root mapping (".") acts as a
    fallback for all namespaces.

    Loaded from `config/structure.yaml` in the project root.

    Example YAML:
        mappings:
          source.raw:
            default_connection_name: pg_main
            database_name: main_db
            schema_name: raw
    """

    mappings: dict[str, StructureProjectMapping]

    def get_mapping(self, namespace: str) -> StructureProjectMapping:
        """Return the mapping for the given namespace.

        Walks up the namespace hierarchy to find the closest matching
        mapping. For example, "a.b.c" tries "a.b.c", "a.b", "a",
        then ".".
        """
        nld_namespace = NldNamespace(namespace)
        for ancestor in reversed(nld_namespace.hierarchy):
            if str(ancestor) in self.mappings:
                return self.mappings[str(ancestor)]
        raise ValueError(f"Namespace '{namespace}' not found in structure config")

    def get_namespaces(self) -> list[str]:
        """Return all configured namespace keys."""
        return list(self.mappings.keys())
