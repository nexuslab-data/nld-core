from nld.structure import Structure


class DuckDBStructure(Structure):
    """Structure subclass with typed DuckDB-specific properties.

    Provides typed property accessors for database_name and schema_name
    that read from the generic properties dictionary.
    """

    @property
    def database_name(self) -> str | None:
        """Get the database name from the properties dictionary."""
        return self.get_properties().get("database")

    @property
    def schema_name(self) -> str | None:
        """Get the schema name from the properties dictionary."""
        return self.get_properties().get("schema")
