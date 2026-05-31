from click.exceptions import ClickException


class ExceptionExit(ClickException):
    """Wraps exceptions without results thrown while invoking nld commands."""

    def __init__(self, exception: Exception) -> None:
        super().__init__(exception.__str__())
        self.exception = exception
