from typing import TYPE_CHECKING

from nld.pydantic import NldBaseModel
from nld.service.file_output_service import FileOutputService

if TYPE_CHECKING:
    from nld.structure.structure import Structure, StructureAdapter


class StructureBuilder(NldBaseModel):
    structure: "Structure"
    structure_adapter: "StructureAdapter"
    output_folder_name: str | None = None

    def build(self) -> None:
        """Builds and writes a new data structure into YAML format."""
        file_output_service = FileOutputService(
            root_folder_path=".",
            override_output_folder_path=self.output_folder_name,
        )

        new_structure = self.structure_adapter.adapt_structure(
            original_structure=self.structure
        )

        file_output_service.write_yaml_file(
            new_structure, internal_folder_name="structure"
        )
