from enum import Enum
from typing import Any


class EventLevel(int, Enum):
    CRITICAL = 50
    FATAL = CRITICAL
    ERROR = 40
    WARNING = 30
    WARN = WARNING
    INFO = 20
    DEBUG = 10
    TRACE = 7
    TEST = 5


class BaseEvent:
    def __init__(self, **kwargs: dict[str, Any]) -> None:
        for k, v in kwargs.items():
            self.__setattr__(k, v)

    def level(self) -> EventLevel:
        return EventLevel.DEBUG

    def message(self) -> str:
        raise Exception("message() not implemented for event")

    def code(self) -> str:
        raise Exception("code() not implemented for event")


class TestEvent(BaseEvent):
    def level(self) -> EventLevel:
        return EventLevel.TEST


class TraceEvent(BaseEvent):
    def level(self) -> EventLevel:
        return EventLevel.TRACE


class DebugEvent(BaseEvent):
    def level(self) -> EventLevel:
        return EventLevel.DEBUG


class InfoEvent(BaseEvent):
    def level(self) -> EventLevel:
        return EventLevel.INFO


class WarnEvent(BaseEvent):
    def level(self) -> EventLevel:
        return EventLevel.WARN


class ErrorEvent(BaseEvent):
    def level(self) -> EventLevel:
        return EventLevel.ERROR


class StandardEvent(BaseEvent):
    def __init__(self, msg: str, **kwargs: dict[str, Any]) -> None:
        super().__init__(**kwargs)
        self.msg = msg

    def code(self) -> str:
        return "A-000"

    def message(self) -> str:
        return f"{self.msg}"


class StandardTestEvent(StandardEvent):
    def level(self) -> EventLevel:
        return EventLevel.TEST


class StandardTraceEvent(StandardEvent):
    def level(self) -> EventLevel:
        return EventLevel.TRACE


class StandardDebugEvent(StandardEvent):
    def level(self) -> EventLevel:
        return EventLevel.DEBUG


class StandardInfoEvent(StandardEvent):
    def level(self) -> EventLevel:
        return EventLevel.INFO


class StandardWarningEvent(StandardEvent):
    def level(self) -> EventLevel:
        return EventLevel.WARNING


class StandardErrorEvent(StandardEvent):
    def level(self) -> EventLevel:
        return EventLevel.ERROR
