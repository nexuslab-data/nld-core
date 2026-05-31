import abc

from nld.connector.s3_blob_storage import S3ObjectStorageConnector
from nld.flow.backend.s3_blob_storage import S3BackendMixin
from nld.flow.execution.manager import ExecutionBackendStateManager


class S3ExecutionBackendStateManagerBase(
    S3BackendMixin,
    ExecutionBackendStateManager[S3ObjectStorageConnector],
    abc.ABC,
):
    """
    Base class for S3 execution backend state managers.

    Combines S3BackendMixin functionality with ExecutionBackendStateManager
    for different engine implementations (pydantic, duckdb).
    """

    param_definitions = [*S3BackendMixin.s3_param_definitions]
