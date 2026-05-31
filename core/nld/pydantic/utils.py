from typing import Literal

from .base_model import NldBaseModel
from .namespace import NldNamespace
from .namespaced_base_model_wrapper import (
    NldNamespacedBaseModelWrapper,
)

ROOT_NAMESPACE: str = NldNamespace.ROOT_VALUE


def select_by_namespace_priority[W: "NldNamespacedBaseModelWrapper[NldBaseModel]"](
    entities: list[W],
    priority: Literal["root", "deepest"] = "root",
) -> W:
    """
    Select an entity from a list based on namespace priority.

    Args:
        entities: List of wrapped entities with different namespaces
        priority: Selection strategy - "root" for closest to root namespace,
                  "deepest" for furthest from root namespace

    Returns:
        The selected entity wrapper based on the priority strategy

    Raises:
        ValueError: If entities list is empty

    Example:
        >>> entities = [
        ...     NldNamespacedBaseModelWrapper(model=m1, namespace="."),
        ...     NldNamespacedBaseModelWrapper(model=m2, namespace="ns1.ns2"),
        ... ]
        >>> select_by_namespace_priority(entities, priority="root")
        <wrapper with namespace ".">
    """
    if not entities:
        raise ValueError("Cannot select from empty entities list")

    if len(entities) == 1:
        return entities[0]

    def namespace_depth(wrapper: W) -> int:
        return NldNamespace(wrapper.namespace).depth

    sorted_entities = sorted(
        entities,
        key=namespace_depth,
    )

    if priority == "root":
        return sorted_entities[0]
    else:
        return sorted_entities[-1]
