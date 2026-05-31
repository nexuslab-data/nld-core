import copy
import logging
from typing import Self, cast

from nld.exceptions import BaseModelDeepCopyException
from nld.logging import BaseEvent, EventLevel, NldLogger


class NldMixIn:
    """MixIn for all the NLD classes.

    Initializes the local logger.
    """

    def __init__(self) -> None:
        self._init_logger()

    def _init_logger(self) -> None:
        self.logger = cast(NldLogger, logging.getLogger(self.__class__.__name__))

    def log_event(self, event: BaseEvent) -> None:
        self.logger.log_event(event)

    def log_debug(self, message: str) -> None:
        self.logger.log(EventLevel.DEBUG, message)

    def log_info(self, message: str) -> None:
        self.logger.log(EventLevel.INFO, message)

    def log_warn(self, message: str) -> None:
        self.logger.log(EventLevel.WARN, message)

    def log_error(self, message: str) -> None:
        self.logger.log(EventLevel.ERROR, message)

    @classmethod
    def deep_copy(cls, self: Self) -> Self:
        """Creates a deep copy of this object.

        Returns:
            A new object cloned from this object instance.
        """
        if not isinstance(self, cls):
            raise BaseModelDeepCopyException(self, cls)
        return copy.deepcopy(self)
