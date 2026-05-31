from __future__ import annotations

import abc
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nld.connector.s3_blob_storage import S3ObjectStorageConnector, S3Structure
from nld.flow.backend.utils import BackendStandardFolderNames
from nld.parameters import ExecutionParameterDefinition
from nld.utils import clean_folder_path, join_paths

if TYPE_CHECKING:
    from nld.flow.definition.flow_definition import DataFlowDefinition


class S3BackendMixin(abc.ABC):
    """
    Mixin providing common S3 backend functionality.

    This mixin contains shared properties and methods for S3-based state
    backend managers, avoiding code duplication between execution and
    incremental backends.

    Requires the implementing class to have:
        - backend_connector: S3ObjectStorageConnector
        - parameters: dict[str, Any]
    """

    # Type hints for attributes that must be provided by the implementing class
    backend_connector: S3ObjectStorageConnector
    parameters: dict[str, Any]

    # Common parameter definitions for S3 backends
    s3_param_definitions: list[str | ExecutionParameterDefinition] = [
        ExecutionParameterDefinition(name="processing_sub_folder_name", mandatory=True),
        ExecutionParameterDefinition(name="local_state_dir", mandatory=True),
    ]

    @property
    def s3_root_path(self) -> str:
        """Get the S3 root path from parameters."""
        return self.parameters["s3_root_path"]  # type: ignore[no-any-return]

    @property
    def local_state_dir(self) -> Path:
        """Get the local state directory from parameters."""
        return Path(self.parameters["local_state_dir"])

    @property
    def processing_sub_folder_name(self) -> str:
        """Get the processing sub folder name from parameters."""
        return self.parameters["processing_sub_folder_name"]  # type: ignore[no-any-return]

    @property
    def backend_state_root_path(self) -> str:
        """Get the backend state root path."""
        return join_paths(self.s3_root_path, BackendStandardFolderNames.STATE)

    @property
    def backend_state_for_processing_path(self) -> str:
        """Get the backend state path for processing."""
        return join_paths(
            self.s3_root_path,
            self.processing_sub_folder_name,
            BackendStandardFolderNames.STATE,
        )

    @property
    @abc.abstractmethod
    def file_format(self) -> str:
        """Get the storage format. Must be implemented by subclasses."""
        ...

    @classmethod
    def determine_parameters_for_flow_definition(
        cls,
        data_flow_definition: DataFlowDefinition | None,
    ) -> dict[str, Any]:
        """Derive ``s3_root_path`` from the flow's typed S3 target structure.

        Shared by every S3 backend manager (execution and incremental,
        pydantic and duckdb): each one subclasses ``S3BackendMixin`` and
        inherits this hook so derivation behaves identically across all
        of them.
        """
        params: dict[str, Any] = {}
        if data_flow_definition is None:
            return params
        if data_flow_definition.target_structure is None:
            return params
        target_structure = data_flow_definition.resolve_target_structure()
        if isinstance(target_structure, S3Structure):
            params["s3_root_path"] = target_structure.s3_root_path
        return params

    def _upload_file_to_state_at_root_folder(
        self,
        local_paths: Iterable[Path],
    ) -> None:
        """Upload files to the state root folder in S3."""
        self.backend_connector.upload_files_from_local_paths(
            base_prefix=clean_folder_path(self.backend_state_root_path),
            file_paths=local_paths,
        )

    def _upload_file_to_state_in_process_folder(
        self,
        local_path: Path,
    ) -> None:
        """Upload a file to the process-specific state folder in S3."""
        self.backend_connector.upload_file_from_local_path(
            local_file_path=str(local_path),
            obj_storage_path=f"{self.backend_state_for_processing_path}/{local_path.name}",
        )
