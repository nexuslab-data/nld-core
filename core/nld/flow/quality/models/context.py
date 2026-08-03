from typing import Any

from pydantic import ConfigDict

from nld.pydantic import NldBaseModel


class DataQualityContext(NldBaseModel):
    """Runtime context handed to the quality rules for one flow target.

    Built once per run and owned by the quality service: the connector is
    the flow's target connector (typed loosely because connectors are not
    Pydantic models), ``table_path`` the qualified ``schema.table`` the
    write strategy targeted, and ``baseline_row_count`` the pre-write
    ``COUNT(*)`` captured for row-growth checks (None when not captured).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    baseline_row_count: int | None = None
    connector: Any
    table_path: str
