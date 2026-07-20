from nld.exceptions import NldRuntimeException


class NldSchedulingError(NldRuntimeException):
    CODE = 1400
    MESSAGE = "NLD Scheduling Error"


class NldSchedulingReferenceError(NldSchedulingError):
    CODE = 1401
    MESSAGE = "NLD Scheduling Reference Error"


class NldSchedulingCycleError(NldSchedulingError):
    CODE = 1402
    MESSAGE = "NLD Scheduling Cycle Error"

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        path = " -> ".join(cycle)
        self.message = f"Dependency cycle detected in scheduling graph: {path}"
        super().__init__(self.message)
