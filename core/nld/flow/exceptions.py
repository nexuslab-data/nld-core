from nld.exceptions import NldRuntimeException


class InvalidFlowRequestParametersException(NldRuntimeException):
    CODE = 30001
    MESSAGE = "Invalid Flow Request Parameters Exception"

    def __init__(
        self,
        flow_namespace: str,
        flow_name: str,
        flow_instance_name: str,
        message: str,
    ) -> None:
        self.message = (
            f"Invalid Flow Request Parameters for flow: "
            f"{flow_namespace}/{flow_name}/{flow_instance_name} "
            f"with message: {message}"
        )
        super().__init__(self.message)


class FlowException(NldRuntimeException):
    CODE = 42001
    MESSAGE = "Flow Standard Exception"

    def __init__(
        self,
        message: str,
    ) -> None:
        self.message = message
        super().__init__(self.message)


class NoPlannedStateException(NldRuntimeException):
    CODE = 42002
    MESSAGE = "No Planned State Exception"

    def __init__(
        self,
        flow_namespace: str,
        flow_name: str,
    ) -> None:
        self.message = (
            f"No planned state available for flow "
            f"{flow_namespace}/{flow_name} but the '--planned-state-strategy "
            f"strict' option requires one."
        )
        super().__init__(self.message)


class StalePlannedStateException(NldRuntimeException):
    CODE = 42003
    MESSAGE = "Stale Planned State Exception"

    def __init__(
        self,
        plan_state_uid: str,
    ) -> None:
        self.message = (
            f"Planned state {plan_state_uid} is stale relative to the latest "
            f"incremental state and the '--planned-state-strategy strict' "
            f"option forbids recomputing it."
        )
        super().__init__(self.message)
