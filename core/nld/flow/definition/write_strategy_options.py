from pydantic import ConfigDict

from nld.flow.utils.flow_update_strategy import (
    OVERWRITE_MODE_LITERAL,
    OverwriteModes,
)
from nld.pydantic import NldBaseModel


class WriteStrategyOptions(NldBaseModel):
    """Options tuning how the flow's write strategy writes its target.

    Declared next to ``write_strategy`` in the flow YAML. Every option
    defaults to ``None`` so an undeclared option keeps the strategy's
    built-in behaviour and leaves the flow definition hash unchanged.

    Example YAML:
        write_strategy: OVERWRITE
        write_strategy_options:
          overwrite_mode: replace
    """

    # A misspelled option would otherwise be silently dropped and the flow
    # would run with the strategy's default behaviour.
    model_config = ConfigDict(extra="forbid")

    overwrite_mode: OVERWRITE_MODE_LITERAL | None = None

    def is_overwrite_replace(self) -> bool:
        """Whether the OVERWRITE strategy must replace the whole table."""
        return self.overwrite_mode == OverwriteModes.REPLACE.value
