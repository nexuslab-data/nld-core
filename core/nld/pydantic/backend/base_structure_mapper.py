from typing import TYPE_CHECKING, Any, get_args

from nld.exceptions import NotImplementedMethodException
from nld.pydantic.base_model import NldBaseModel

if TYPE_CHECKING:
    from nld.structure import Field, Structure


class BasePydanticStructureMapper:
    @staticmethod
    def map_pydantic_type_to_target(python_type: Any) -> Any:
        """
        Map a Python type to the target backend type.

        Args:
            python_type: Python type annotation from Pydantic field

        Returns:
            Target data type
        """
        raise NotImplementedMethodException(
            BasePydanticStructureMapper, "map_pydantic_type_to_target"
        )

    @staticmethod
    def is_nullable(python_type: Any) -> bool:
        """
        Check if a Python type is nullable (Optional).

        Args:
            python_type: Python type annotation from Pydantic field

        Returns:
            True if the type is nullable (Optional), False otherwise
        """
        # Handle None type directly
        if python_type is type(None):
            return True

        # Check for Union types (Optional[T] is Union[T, None])
        if hasattr(python_type, "__args__"):
            args = get_args(python_type)
            if type(None) in args:
                return True

        return False

    @classmethod
    def get_structure(cls, model_class: type[NldBaseModel]) -> "Structure":
        raise NotImplementedMethodException(cls, "get_structure")

    @classmethod
    def get_field_definitions(
        cls, model_class: type[NldBaseModel]
    ) -> dict[str, "Field"]:
        raise NotImplementedMethodException(cls, "get_field_definitions")

    @staticmethod
    def prepare_value_for_target(value: Any) -> Any:
        raise NotImplementedMethodException(
            BasePydanticStructureMapper, "prepare_value_for_target"
        )
