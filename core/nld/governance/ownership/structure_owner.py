from nld.pydantic import NldNamespacedBaseModelWrapper

from .base import OwnerBase


class StructureOwner(OwnerBase):
    """Data-responsibility owner of a structure (or structure namespace).

    Declared at a source / structure namespace and inherited by every structure
    beneath it (nearest declaration wins). A downstream structure with no
    declaration of its own resolves its data owner(s) by walking lineage up to
    the owned sources — and is owned jointly by all of them.
    """


class NamespacedStructureOwner(NldNamespacedBaseModelWrapper[StructureOwner]):
    """StructureOwner wrapped with namespace information."""
