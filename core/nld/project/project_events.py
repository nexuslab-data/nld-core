from nld.logging import ErrorEvent, InfoEvent


####################################################################
##                      Project events                            ##
####################################################################
class ProjectMissingYamlFile(ErrorEvent):
    def __init__(self, path: str):
        self.path = path

    def code(self) -> str:
        return "PRJ-001"

    def message(self) -> str:
        return f"No nld_project.yml found at expected path {self.path}"


class ProjectMissingFolder(ErrorEvent):
    def __init__(self, path: str):
        self.path = path

    def code(self) -> str:
        return "PRJ-002"

    def message(self) -> str:
        return f"No folder found at expected path {self.path}"


class ProjectAlreadyInitializedFolder(ErrorEvent):
    def __init__(self, path: str):
        self.path = path

    def code(self) -> str:
        return "PRJ-003"

    def message(self) -> str:
        return f"Project folder is already initialized at path {self.path}"


class ProjectInitializationFolderError(ErrorEvent):
    def __init__(self, path: str):
        self.path = path

    def code(self) -> str:
        return "PRJ-004"

    def message(self) -> str:
        return (
            f"No folder is available at path {self.path}. "
            "Project can be initialized only on an existing folder."
        )


class ProjectInitializationConfigError(ErrorEvent):
    def __init__(self, path: str):
        self.path = path

    def code(self) -> str:
        return "PRJ-005"

    def message(self) -> str:
        return (
            f"Configuration file already exists at path {self.path}. "
            "Project can be initialized only on an un-initialized folder."
        )


class ProjectSubFolderAlreadyInitializedError(ErrorEvent):
    def __init__(self, path: str):
        self.path = path

    def code(self) -> str:
        return "PRJ-006"

    def message(self) -> str:
        return (
            f"The folder already exists at path {self.path}. "
            "Project cannot be initialized with sub folders already created"
        )


class ProjectInitializedSuccessfully(InfoEvent):
    def __init__(self, path: str):
        self.path = path

    def code(self) -> str:
        return "PRJ-007"

    def message(self) -> str:
        return f"Project was initialized successfully at path {self.path}."
