from pydantic import ConfigDict

from nld.pydantic import NldBaseModel


class StructureNamespace(NldBaseModel):
    model_config = ConfigDict(frozen=True)

    databank: str
    catalog: str | None = None
    namespace: str | None = None

    def __hash__(self) -> int:
        return hash(repr(self))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return False
        return self.model_dump() == other.model_dump()

    def __str__(self) -> str:
        return ".".join([self.databank, self.catalog or "", self.namespace or ""])
