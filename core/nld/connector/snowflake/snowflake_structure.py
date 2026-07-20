from nld.structure import Structure


class SnowflakeStructure(Structure):
    """Structure subclass with typed Snowflake-specific properties.

    Provides typed property accessors for database_name, schema_name
    and warehouse that read from the generic properties dictionary.
    Snowflake objects live in a two-level namespace
    (``database.schema``) and are always read/written through a
    warehouse, so all three are captured when known.
    """

    @property
    def database_name(self) -> str | None:
        """Get the database name from the properties dictionary."""
        return self.get_properties().get("database")

    @property
    def schema_name(self) -> str | None:
        """Get the schema name from the properties dictionary."""
        return self.get_properties().get("schema")

    @property
    def warehouse(self) -> str | None:
        """Get the warehouse from the properties dictionary."""
        return self.get_properties().get("warehouse")
