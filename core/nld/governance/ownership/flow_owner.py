from nld.pydantic import NldNamespacedBaseModelWrapper

from .base import OwnerBase


class FlowOwner(OwnerBase):
    """Technical-execution owner of a flow (or flow namespace).

    The team responsible for *running* the flow — scheduling, retries, failures,
    infrastructure — which is explicitly not data quality. Declared at a flow /
    flow namespace and inherited by every flow beneath it (nearest declaration
    wins). It becomes the technical owner of the structure the flow produces and
    does not propagate along data lineage.
    """


class NamespacedFlowOwner(NldNamespacedBaseModelWrapper[FlowOwner]):
    """FlowOwner wrapped with namespace information."""
