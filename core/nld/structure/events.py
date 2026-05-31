from nld.logging import ErrorEvent, InfoEvent, WarnEvent

####################################################################
##                      Structure events                          ##
####################################################################


class CreatedStructureUsingAdaptation(InfoEvent):
    def __init__(
        self,
        structure_name: str,
        adapter_name: str,
        original_structure_name: str,
    ):
        self.structure_name = structure_name
        self.adapter_name = adapter_name
        self.original_structure_name = original_structure_name

    def code(self) -> str:
        return "A-001"

    def message(self) -> str:
        return (
            f"Structure {self.structure_name} was created based on the adapter "
            f"{self.adapter_name} from original structure "
            f"{self.original_structure_name}"
        )


class NotAvailableFieldInStructure(ErrorEvent):
    def __init__(self, structure_name: str, field_name: str):
        self.structure_name = structure_name
        self.field_name = field_name

    def code(self) -> str:
        return "A-101"

    def message(self) -> str:
        return (
            f"Field {self.field_name} does not exist in structure {self.structure_name}"
        )


class FieldCharacterisationAlreadySet(WarnEvent):
    def __init__(self, field_name: str, characterisation_name: str):
        self.field_name = field_name
        self.characterisation_name = characterisation_name

    def code(self) -> str:
        return "A-103"

    def message(self) -> str:
        return (
            f"Characterisation {self.characterisation_name} is already set "
            f"on field {self.field_name}"
        )
