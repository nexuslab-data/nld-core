from nld.logging import DebugEvent
from nld.pydantic import NldBaseModel, NldNamedBaseModel


class DataClassReadFromDirectoryStartEvent(DebugEvent):
    def __init__(
        self,
        data_class: type[NldBaseModel | NldNamedBaseModel],
        root_path: str,
    ) -> None:
        super().__init__()
        self.data_class = data_class
        self.root_path = root_path

    def code(self) -> str:
        return "M-101"

    def message(self) -> str:
        return f"{self.data_class.__name__} load started on folder : {self.root_path}"


class DataClassReadFromDirectoryCompletedSuccessfullyEvent(DebugEvent):
    def __init__(
        self,
        data_class: type[NldBaseModel | NldNamedBaseModel],
    ) -> None:
        super().__init__()
        self.data_class = data_class

    def code(self) -> str:
        return "M-102"

    def message(self) -> str:
        return f"{self.data_class.__name__} load completed"
