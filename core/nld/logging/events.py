import os

from .base import ErrorEvent, InfoEvent

####################################################################
##                       Generic events                           ##
##                       Event Class : X                          ##
####################################################################


class MissingMandatoryArgument(ErrorEvent):
    def __init__(self, argument_name: str, method_name: str, object_type: type) -> None:
        self.argument_name = argument_name
        self.method_name = method_name
        self.object_type = object_type

    def code(self) -> str:
        return "X-001"

    def message(self) -> str:
        return (
            f"Missing mandatory argument {self.argument_name} on call of "
            f"method '{self.method_name}' on {self.object_type.__name__}"
        )


####################################################################
##                    Data Classes events                         ##
##                       Event Class : M                          ##
####################################################################
class DataClassSchemaNonAuthorizedAttribute(ErrorEvent):
    def __init__(
        self,
        schema_name: str,
        additional_fields: list[str],
    ) -> None:
        self.schema_name = schema_name
        self.additional_fields = additional_fields

    def code(self) -> str:
        return "M-001"

    def message(self) -> str:
        return (
            f"Additional arguments in dictionary for object schema: "
            f"{self.schema_name}. List of non-authorized fields: "
            f"{', '.join(self.additional_fields)}"
        )


class DataClassSchemaMissingMandatoryAttribute(ErrorEvent):
    def __init__(
        self,
        schema_name: str,
        missing_mandatory_fields: list[str],
    ) -> None:
        self.schema_name = schema_name
        self.missing_mandatory_fields = missing_mandatory_fields

    def code(self) -> str:
        return "M-002"

    def message(self) -> str:
        return (
            f"Some mandatory fields are missing in dictionary for object "
            f"schema: {self.schema_name}. List of missing mandatory fields: "
            f"{', '.join(self.missing_mandatory_fields)}"
        )


class DataClassSchemaSubClassError(ErrorEvent):
    def __init__(
        self,
        schema_name: str,
        attribute_name: str,
        sub_class_name: str,
    ) -> None:
        self.schema_name = schema_name
        self.attribute_name = attribute_name
        self.sub_class_name = sub_class_name

    def code(self) -> str:
        return "M-003"

    def message(self) -> str:
        return (
            f"For Schema {self.schema_name}, attribute {self.attribute_name} for "
            f"sub class {self.sub_class_name} does not match the expected pattern."
        )


####################################################################
##                         CSV events                             ##
####################################################################
class CSVFileReadSuccessful(InfoEvent):
    def __init__(self, object_type_name: str, file_path: str):
        self.object_type_name = object_type_name
        self.file_path = file_path

    def code(self) -> str:
        return "CSV-001"

    def message(self) -> str:
        return f"{self.object_type_name} was loaded from file {self.file_path}"


class CSVFileWriteSuccessful(InfoEvent):
    def __init__(self, object_type_name: str, file_path: str):
        self.object_type_name = object_type_name
        self.file_path = file_path

    def code(self) -> str:
        return "CSV-002"

    def message(self) -> str:
        return (
            f"{self.object_type_name} export to CSV successful. "
            f"File was exported at {os.path.abspath(self.file_path)}"
        )


####################################################################
##                         Task events                            ##
####################################################################
