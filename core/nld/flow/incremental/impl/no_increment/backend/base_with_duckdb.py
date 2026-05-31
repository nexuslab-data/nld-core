from typing import Any

from nld.connector.base.connector import DataConnector
from nld.flow.incremental.impl.no_increment.backend.base_with_pydantic import (
    NoIncrementStateBackendManager as _BaseManager,
)


class NoIncrementStateBackendManager[DATA_CONNECTOR: DataConnector[Any]](
    _BaseManager[DATA_CONNECTOR],
):
    """
    No Increment - DuckDB - Backend State Manager

    Inherits from pydantic version since no_increment is a pass-through
    that doesn't require engine-specific implementation.
    """

    pass
