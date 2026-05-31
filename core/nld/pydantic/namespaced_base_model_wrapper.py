from .base_model import NldBaseModel
from .named_base_model import NldNamedBaseModel
from .namespace import NldNamespace


class NldNamespacedBaseModelWrapper[T: NldBaseModel | NldNamedBaseModel]:
    """
    Wraps NldBaseModel or NldNamedBaseModel with namespace information.

    This class combines a namespace string with an NldBaseModel instance,
    providing a structured way to return models with their namespace context.

    Type parameter T specifies the specific model type being wrapped.

    Example:
        >>> wrapper = NldNamespacedBaseModelWrapper[MyModel](
        ...     namespace="level1.level2",
        ...     model=my_model_instance
        ... )
        >>> print(wrapper.namespace)
        "level1.level2"
        >>> print(wrapper.model)
        <MyModel instance>
    """

    ROOT_NAMESPACE: str = NldNamespace.ROOT_VALUE

    def __init__(self, model: T, namespace: str) -> None:
        """
        Initialize the wrapper.

        Args:
            model: The model instance to wrap
            namespace: The namespace string
        """
        self.model: T = model
        self.namespace: NldNamespace = NldNamespace(namespace)

    @property
    def id(self) -> str:
        """Build a unique identifier from namespace and model name.

        Raises:
            TypeError: If the wrapped model is not an NldNamedBaseModel.
        """
        if not isinstance(self.model, NldNamedBaseModel):
            raise TypeError(
                f"id is only available for NldNamedBaseModel, "
                f"got {type(self.model).__name__}"
            )
        if self.namespace.is_root:
            return self.model.name
        return f"{self.namespace}.{self.model.name}"
