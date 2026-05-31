from nld.exceptions import NldRuntimeException

####################################################################
##                     Project exceptions                         ##
####################################################################


class NldConfigError(NldRuntimeException):
    CODE = 1001
    MESSAGE = "NLD Configuration Error"


class NldProjectError(NldConfigError):
    CODE = 1101
    MESSAGE = "NLD Project Error"


class NldMissingProjectYamlFile(NldProjectError):
    CODE = 1102
    MESSAGE = "NLD Missing Project YAML File"

    def __init__(self, path: str) -> None:
        self.message = f"No nld_project.yml found at expected path {path}"
        super().__init__(self.message)


class NldProjectYamlMissingMandatoryKeys(NldProjectError):
    CODE = 1103
    MESSAGE = "NLD Project YAML File Missing Mandatory Keys"

    def __init__(self, missing_keys: list[str]) -> None:
        keys = ", ".join(missing_keys)
        self.message = f"The project yaml is missing the mandatory keys: {keys}"
        super().__init__(self.message)


class NldMissingProjectFolder(NldProjectError):
    CODE = 1110
    MESSAGE = "NLD Missing Project Folder"

    def __init__(self, folder_name: str, path: str) -> None:
        self.message = f"No {folder_name} found at expected path {path}"
        super().__init__(self.message)
