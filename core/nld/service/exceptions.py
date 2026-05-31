from nld.exceptions import NldRuntimeException
from nld.pydantic import NldBaseModel


class ObjectReadNoDirectoryException(NldRuntimeException):
    CODE = 21101
    MESSAGE = "No directory found during the read of object"

    def __init__(self, folder_path: str, data_class: type[NldBaseModel]) -> None:
        self.message = (
            f"Load from folder {folder_path} for object {data_class.__name__} "
            f"failed due to non-existant folder."
        )
        super().__init__(self.message)
