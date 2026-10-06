from __future__ import annotations

from typing import Any

from nld.exceptions import NldRuntimeException
from nld.parameters import ExecutionParameterDefinition
from nld.service import FileOutputService
from nld.structure import Structure
from nld.task import StandardTask
from nld.task.context import NldExecutionContext


class ConnectionGetStructureTask(StandardTask):
    """Task to extract database structure from a connection.

    This task connects to a database and extracts metadata about
    tables, views, columns, primary keys, and unique constraints.
    Output files are organized into namespace folders derived from
    the database and schema of each extracted structure.

    Example:
        >>> task = ConnectionGetStructureTask()
        >>> task.run(
        ...     connection_name="my_connection",
        ...     schema="public",
        ... )
    """

    init_params = []
    run_params = [
        ExecutionParameterDefinition(name="connection_name", mandatory=True),
        ExecutionParameterDefinition(name="profile_name", mandatory=False),
        ExecutionParameterDefinition(name="database", mandatory=False),
        ExecutionParameterDefinition(name="namespace", mandatory=False),
        ExecutionParameterDefinition(name="schema", mandatory=False),
        ExecutionParameterDefinition(name="object", mandatory=False),
    ]

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the task."""
        super().__init__(**kwargs)
        self.execution_context = NldExecutionContext.require_current()

    def run(  # type: ignore[override]
        self,
        connection_name: str,
        profile_name: str | None = None,
        database: str | None = None,
        namespace: str | None = None,
        schema: str | None = None,
        object: str | None = None,
        **kwargs: Any,
    ) -> bool:
        """Execute the structure extraction.

        Args:
            connection_name: Name of the connection to use.
            profile_name: Optional connection profile to use. When
                omitted, the connection's default profile is used.
            database: Optional database name. Passed to the structure
                reader for scoping the extraction.
            namespace: Optional dot-separated namespace
                (e.g. "source.raw"). When provided, it is used
                instead of the auto-derived database.schema namespace.
            schema: Optional schema name to filter by.
            object: Optional table/view name to filter by.
            **kwargs: Additional keyword arguments.

        Returns:
            True if extraction was successful, False otherwise.

        Raises:
            NldRuntimeException: If the connector does not support
                structure extraction.
        """
        connector = self.execution_context.get_data_connector(
            connection_name,
            profile_name=profile_name,
            open_connection=True,
        )

        reader = connector.get_structure_reader()
        if reader is None:
            msg = (
                f"Connection '{connection_name}' does not support "
                f"structure extraction. "
                f"Connector type: {connector.connection_wrapper.type}"
            )
            raise NldRuntimeException(msg)

        structures = reader.extract_structures(
            database=database,
            schema=schema,
            object_name=object,
        )

        self._output_structures(
            structures,
            namespace=namespace,
        )

        self.log_info(f"Extracted {len(structures)} structure(s)")
        return True

    def _build_structure_namespace(
        self,
        structure: Structure,
        namespace: str | None = None,
    ) -> str:
        """Build a dot-separated namespace for the structure.

        When a namespace is provided, it is used directly.
        Otherwise the namespace is derived from the database and
        schema stored in the structure's properties dict.

        Args:
            structure: The structure to derive the namespace from.
            namespace: Optional namespace to use as-is.

        Returns:
            Dot-separated namespace string (e.g. "mydb.public").
        """
        if namespace:
            return namespace

        properties = structure.get_properties()
        parts: list[str] = []

        if properties.get("database"):
            parts.append(properties["database"])

        if properties.get("schema"):
            parts.append(properties["schema"])

        return ".".join(parts)

    def _output_structures(
        self,
        structures: list[Structure],
        namespace: str | None = None,
    ) -> None:
        """Write each structure as a YAML file via FileOutputService.

        Files are organized into folders derived from each structure's
        database and schema (e.g. structure/mydb/public/users.yml).
        """
        file_output_service = FileOutputService(
            root_folder_path=".",
            entity_layout=self.execution_context.entity_layout,
        )

        for structure in structures:
            resolved_namespace = self._build_structure_namespace(
                structure,
                namespace=namespace,
            )
            file_output_service.write_yaml_file(
                structure,
                internal_folder_name="structure",
                namespace=resolved_namespace if resolved_namespace else None,
            )
