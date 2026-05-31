from enum import StrEnum


class NldStrEnum(StrEnum):
    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls.values()

    @classmethod
    def values(cls) -> set[str]:
        return set(cls.__members__.values())

    def __str__(self) -> str:
        return self.value
