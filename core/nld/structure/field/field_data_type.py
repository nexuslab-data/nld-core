import re

from nld.pydantic import NldBaseModel


class FieldDataType(NldBaseModel):
    data_type: str = "STRING"
    length: int = 0
    precision: int = 0

    def as_tuple(self) -> tuple[str, int, int]:
        return self.data_type, self.length, self.precision

    @classmethod
    def from_string(cls, data_type_str: str) -> "FieldDataType":
        """Parses compact format like VARCHAR(100,0) or VARCHAR(100) or VARCHAR.

        Supports multi-word data types like DOUBLE PRECISION or CHARACTER VARYING.

        Args:
            data_type_str: The data type string in compact format.

        Returns:
            A FieldDataType instance with parsed values.
        """
        match = re.match(r"([\w\s]+?)(?:\((\d+)(?:,(\d+))?\))?\s*$", data_type_str)
        if match:
            data_type = match.group(1).strip()
            length = int(match.group(2)) if match.group(2) else 0
            precision = int(match.group(3)) if match.group(3) else 0
            return cls(
                data_type=data_type,
                length=length,
                precision=precision,
            )
        return cls(data_type=data_type_str)

    def __str__(self) -> str:
        """Returns compact format string representation."""
        if self.length == 0 and self.precision == 0:
            return self.data_type
        elif self.precision == 0:
            return f"{self.data_type}({self.length})"
        else:
            return f"{self.data_type}({self.length},{self.precision})"

    def to_compact_string(self) -> str:
        """Returns compact format string representation."""
        return str(self)
