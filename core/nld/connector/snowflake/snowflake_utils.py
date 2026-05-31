from typing import Final

from nld.structure import (
    Field,
    FieldCharacterisation,
    FieldCharacterisationDefinitions,
    Structure,
)
from snowflake.connector.cursor import ResultMetadata
from snowflake.connector.errors import ProgrammingError as SnowflakeProgrammingError

from .snowflake_data_type import (
    SnowflakeDataTypes,
)

SNOWFLAKE_MAX_TEXT_LENGTH: Final[int] = 16777216


class SnowflakeUtil:
    @classmethod
    def get_standard_error_message(cls, error: SnowflakeProgrammingError) -> str:
        return f"Error {error.errno} ({error.sqlstate}): {error.msg} ({error.sfqid})"

    @classmethod
    def get_field_from_result_metadata(cls, result_metadata: ResultMetadata) -> Field:
        return Field(
            name=result_metadata.name.lower(),
            description=None,
            data_type=SnowflakeUtil.get_snowflake_data_type_mapping()[
                result_metadata.type_code
            ],
            length=result_metadata.internal_size or 0,
            precision=result_metadata.scale or 0,
            default_value=None,
            characterisations=(
                [
                    FieldCharacterisation.create_from_definition(
                        FieldCharacterisationDefinitions.MANDATORY
                    )
                ]
                if not result_metadata.is_nullable
                else []
            ),
        )

    @classmethod
    def get_result_error_field(cls) -> Field:
        return Field(
            name="Error Message",
            description=None,
            data_type=SnowflakeDataTypes.TEXT,
            length=SNOWFLAKE_MAX_TEXT_LENGTH,
            precision=0,
            default_value=None,
            characterisations=[],
        )

    @classmethod
    def get_structure_from_result_metadata(
        cls,
        result_metadata_list: list[ResultMetadata],
    ) -> Structure:
        structure = Structure(
            name="ResultSet",
            description=None,
            structure_type="PyDataSet",
            stats={"row_count": 0},
        )
        for result_metadata in result_metadata_list:
            structure.add_field(
                new_field=SnowflakeUtil.get_field_from_result_metadata(result_metadata),
            )
        return structure

    @classmethod
    def get_structure_for_error_result(cls) -> Structure:
        structure = Structure(
            name="ResultSet",
            description=None,
            structure_type="PyDataSet",
            stats={"row_count": 0},
            options=None,
            fields={},
        )
        structure.add_field(
            new_field=SnowflakeUtil.get_result_error_field(),
        )
        return structure

    @classmethod
    def get_snowflake_data_type_mapping(cls) -> dict[int, str]:
        return {
            0: SnowflakeDataTypes.NUMBER.value,
            1: SnowflakeDataTypes.REAL.value,
            2: SnowflakeDataTypes.TEXT.value,
            3: SnowflakeDataTypes.DATE.value,
            4: SnowflakeDataTypes.TIMESTAMP.value,
            5: SnowflakeDataTypes.VARIANT.value,
            6: SnowflakeDataTypes.TIMESTAMP_LTZ.value,
            7: SnowflakeDataTypes.TIMESTAMP_TZ.value,
            8: SnowflakeDataTypes.TIMESTAMP_NTZ.value,
            9: SnowflakeDataTypes.OBJECT.value,
            10: SnowflakeDataTypes.ARRAY.value,
            11: SnowflakeDataTypes.BINARY.value,
            12: SnowflakeDataTypes.TIME.value,
            13: SnowflakeDataTypes.BOOLEAN.value,
        }
