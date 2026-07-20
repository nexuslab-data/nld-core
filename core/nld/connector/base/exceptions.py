from nld.exceptions import NldRuntimeException


class QueryExecutionException(NldRuntimeException):
    CODE = 30011
    MESSAGE = "Query Execution Exception"

    def __init__(self, error_message: str) -> None:
        self.message = f"{error_message}"
        super().__init__(self.message)


class QueryResultException(NldRuntimeException):
    CODE = 30012
    MESSAGE = "Query Result Exception"

    def __init__(self, error_message: str) -> None:
        self.message = f"{error_message}"
        super().__init__(self.message)


class SingleValueResultException(QueryResultException):
    CODE = 30013
    MESSAGE = "Query Single Value Exception"

    def __init__(self, error_message: str) -> None:
        self.message = (
            "Single value result could not be retrieved. "
            "For more details, check the logs."
        )
        super().__init__(self.message)


class NonSelectQueryException(QueryExecutionException):
    CODE = 30014
    MESSAGE = "Non Select Query Exception"

    def __init__(self, query_type: str) -> None:
        self.message = (
            f"Only read-only SELECT queries are allowed for this operation, "
            f"but the provided query is a '{query_type}' statement."
        )
        super().__init__(self.message)


class NoConnectorAvailableException(NldRuntimeException):
    CODE = 30001
    MESSAGE = "No DB Service available exception"

    def __init__(self, connection_name: str) -> None:
        self.message = f"No db service is available for name:'{connection_name}'"
        super().__init__(self.message)


class ConnectorAlreadyAvailableException(NldRuntimeException):
    CODE = 30002
    MESSAGE = "DB Service is already available exception"

    def __init__(self, connection_name: str) -> None:
        self.message = (
            f"The db service is already available for for name:'{connection_name}'"
        )
        super().__init__(self.message)


class RequestOnClosedConnectionException(NldRuntimeException):
    CODE = 30101
    MESSAGE = "Request on closed connection Exception"

    def __init__(self, connection_name: str, request_desc: str) -> None:
        self.message = (
            f"A request '{request_desc}' was done on the non-opened connection "
            f"{connection_name}. Ensure connection is opened."
        )
        super().__init__(self.message)


class UnavailableConnectionConfigException(NldRuntimeException):
    CODE = 30201
    MESSAGE = "Unavailable connection config exception"

    def __init__(self, connection_name: str) -> None:
        self.message = f"Connection configuration '{connection_name}' is not available"
        super().__init__(self.message)


class UnavailableConnectionProfileException(NldRuntimeException):
    CODE = 30202
    MESSAGE = "Unavailable connection profile exception"

    def __init__(self, connection_name: str, profile_name: str) -> None:
        self.message = (
            f"No profile {profile_name} on connection configuration "
            f"'{connection_name}' is not available"
        )
        super().__init__(self.message)
