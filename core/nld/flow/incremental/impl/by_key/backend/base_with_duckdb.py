from typing import Any

from nld.connector.base.connector import DataConnector
from nld.flow.incremental.impl.by_key.backend.base_with_pydantic import (
    ByKeyStateBackendManager as _BaseManager,
)


class ByKeyStateBackendManager[DATA_CONNECTOR: DataConnector[Any]](
    _BaseManager[DATA_CONNECTOR],
):
    """
    Abstract base class for by_key DuckDB state backend managers.

    Inherits from pydantic version since the abstract interface
    is the same for all engines.
    """

    pass
