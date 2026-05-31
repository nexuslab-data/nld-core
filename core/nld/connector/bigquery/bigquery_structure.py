from nld.structure import Structure


class BigQueryStructure(Structure):
    """Structure subclass with typed BigQuery-specific properties.

    Provides typed property accessors for project_id and dataset_id
    that read from the generic properties dictionary.
    """

    @property
    def project_id(self) -> str | None:
        """Get the project ID from the properties dictionary."""
        return self.get_properties().get("project_id")

    @property
    def dataset_id(self) -> str | None:
        """Get the dataset ID from the properties dictionary."""
        return self.get_properties().get("dataset_id")
