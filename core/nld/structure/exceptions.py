from nld.exceptions import NldRuntimeException


class FieldRemovalException(NldRuntimeException):
    CODE = 20001
    MESSAGE = "Field Removal Exception"

    def __init__(self, field_name: str, structure_name: str) -> None:
        self.message = (
            f"Issue during the removal of the field {field_name} "
            f"on structure {structure_name}"
        )
        super().__init__(self.message)


class FieldAdditionException(NldRuntimeException):
    CODE = 20002
    MESSAGE = "Field Addition Exception"

    def __init__(self, field_name: str, structure_name: str) -> None:
        self.message = (
            f"Issue during the addition of the field {field_name} on structure "
            f"{structure_name} (check log for more information)"
        )
        super().__init__(self.message)


class NotAvailableFieldException(NldRuntimeException):
    CODE = 20011
    MESSAGE = "Field Not Available"

    def __init__(self, structure_name: str, field_name: str):
        self.message = (
            f"Field {field_name} does not exist in structure {structure_name}"
        )
        super().__init__(self.message)
