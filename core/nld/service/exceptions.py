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


class AmbiguousEntityException(NldRuntimeException):
    CODE = 21102
    MESSAGE = "Several entities match the requested name"

    def __init__(
        self,
        entity_label: str,
        entity_key: str,
        namespace: str,
        candidate_ids: list[str],
    ) -> None:
        candidates = ", ".join(candidate_ids)
        self.candidate_ids = candidate_ids
        self.message = (
            f"{entity_label} '{entity_key}' is ambiguous for namespace {namespace}: "
            f"it exists in several namespaces ({candidates}). Qualify the name "
            f"with its namespace or pass the namespace explicitly."
        )
        super().__init__(self.message)


class NamespaceFolderConflictException(NldRuntimeException):
    CODE = 21103
    MESSAGE = "Entities found outside the location owning their namespace"

    def __init__(
        self,
        namespace: str,
        found_directory: str,
        expected_directory: str,
    ) -> None:
        self.message = (
            f"Namespace '{namespace}' is stored in '{expected_directory}', "
            f"but entities of this namespace were found in '{found_directory}'. "
            f"A namespace declared with 'folder: true' (or below one) must keep "
            f"all its entities in its namespace folder: move them to "
            f"'{expected_directory}'."
        )
        super().__init__(self.message)
