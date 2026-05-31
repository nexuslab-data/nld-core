from typing import Final

from pydantic import Field

from nld.pydantic import NldBaseModel, NldNamedBaseModel, NldNamespacedBaseModelWrapper

from .field_data_type import FieldDataType

DEFAULT_DATA_TYPE_FOR_STRING: Final[FieldDataType] = FieldDataType(
    data_type="STRING",
    length=256,
    precision=0,
)


class FieldFormatAdaptionRule(NldBaseModel):
    """
    Field Format Adaptation rule

    This defines an adaptation rule for a field
    """

    allowed_data_types: list[str] = Field(
        default_factory=list,
        description="List of allowed data types for this rule",
    )
    allowed_characterisations: list[str] = Field(
        default_factory=list,
        description="List of allowed characterisations for this rule",
    )
    target_data_type: str = Field(
        default="STRING",
        description="Target data type for transformation",
    )
    length_rule: str = Field(
        default="0",
        description="Rule for calculating field length",
    )
    precision_rule: str = Field(
        default="0",
        description="Rule for calculating field precision",
    )

    def _all_characterisations_allowed(self) -> bool:
        return len(self.allowed_characterisations) == 0

    def is_rule_applicable(
        self, data_type: str, field_characterisation_names: list[str] | None
    ) -> bool:
        if data_type is None:
            return False
        characterisations_lcl = (
            field_characterisation_names
            if field_characterisation_names is not None
            else []
        )
        if data_type in self.allowed_data_types:
            if self._all_characterisations_allowed():
                return True
            else:
                if any(
                    char in self.allowed_characterisations
                    for char in characterisations_lcl
                ):
                    return True
        return False

    def get_adapted_field_format(
        self,
        data_type: str,
        length: int | None = None,
        precision: int | None = None,
    ) -> tuple[str, int, int]:
        new_data_type = self.target_data_type
        new_length = int(
            self.length_rule.format(
                data_type=data_type, length=length, precision=precision
            )
        )
        new_precision = int(
            self.precision_rule.format(
                data_type=data_type, length=length, precision=precision
            )
        )
        return new_data_type, new_length, new_precision


class FieldFormatAdapter(NldNamedBaseModel):
    rules: list[FieldFormatAdaptionRule] = Field(
        default_factory=list,
        description="List of format adaptation rules",
    )
    default_format: FieldDataType | None = Field(
        default=None,
        description="Default format to use if no rules match",
    )
    default_keep_source_format: bool = Field(
        default=True,
        description="Whether to keep source format by default",
    )

    def get_adapted_field_format(
        self,
        data_type: str,
        length: int | None = None,
        precision: int | None = None,
        characterisations: list[str] | None = None,
    ) -> tuple[str, int, int]:
        for rule in self.rules:
            if rule.is_rule_applicable(
                data_type=data_type,
                field_characterisation_names=characterisations,
            ):
                return rule.get_adapted_field_format(data_type, length, precision)
        return (
            (
                self.default_format.as_tuple()
                if self.default_format is not None
                else DEFAULT_DATA_TYPE_FOR_STRING.as_tuple()
            )
            if (not self.default_keep_source_format)
            else (data_type, length or 0, precision or 0)
        )


class NamespacedFieldFormatAdapter(NldNamespacedBaseModelWrapper[FieldFormatAdapter]):
    """FieldFormatAdapter wrapped with namespace information."""
