from typing import TYPE_CHECKING, Any, get_args

from nld.exceptions import NotImplementedMethodException
from nld.logging import log_warn_default
from nld.pydantic.base_model import NldBaseModel

if TYPE_CHECKING:
    from nld.structure import Field, Structure

BUSINESS_KEY_SCHEMA_EXTRA_KEY = "business_key"
DEPRECATED_FUNCTIONAL_KEY_SCHEMA_EXTRA_KEY = "functional_key"


class PydanticModelBusinessKey(NldBaseModel):
    """Business key a Pydantic model declares in its ``json_schema_extra``."""

    field_names: list[str]
    name: str


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

    @staticmethod
    def get_business_key(
        model_class: type[NldBaseModel],
    ) -> PydanticModelBusinessKey | None:
        """Read the business key declared in the model ``json_schema_extra``.

        The key name defaults to ``FUK_<model class name>``, which keeps
        the index names of existing backend tables unchanged. The former
        ``functional_key`` entry is still read until a future release, with
        a deprecation warning naming the model.

        Example:
            >>> class StateRow(NldBaseModel):
            ...     model_config = ConfigDict(
            ...         json_schema_extra={
            ...             "business_key": {
            ...                 "fields": ["flow_name"],
            ...                 "name": "fk_state",
            ...             },
            ...         },
            ...     )
        """
        model_config = getattr(model_class, "model_config", None)
        json_schema_extra = (
            model_config.get("json_schema_extra") if model_config else None
        )
        if not isinstance(json_schema_extra, dict):
            return None
        business_key = json_schema_extra.get(BUSINESS_KEY_SCHEMA_EXTRA_KEY)
        if (
            business_key is None
            and DEPRECATED_FUNCTIONAL_KEY_SCHEMA_EXTRA_KEY in json_schema_extra
        ):
            log_warn_default(
                f"Deprecated json_schema_extra entry "
                f"'{DEPRECATED_FUNCTIONAL_KEY_SCHEMA_EXTRA_KEY}' in model "
                f"'{model_class.__name__}', rename it to "
                f"'{BUSINESS_KEY_SCHEMA_EXTRA_KEY}': the old name will be "
                f"removed in a future release",
            )
            business_key = json_schema_extra[DEPRECATED_FUNCTIONAL_KEY_SCHEMA_EXTRA_KEY]
        if not isinstance(business_key, dict):
            return None
        field_names = [str(field_name) for field_name in business_key.get("fields", [])]
        if not field_names:
            return None
        return PydanticModelBusinessKey(
            field_names=field_names,
            name=str(business_key.get("name", f"FUK_{model_class.__name__}")),
        )

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
