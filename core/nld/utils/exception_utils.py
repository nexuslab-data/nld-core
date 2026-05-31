import traceback


def format_exception_chain(exception: BaseException) -> str:
    """Format an exception together with its full ``__cause__`` / ``__context__`` chain.

    Walks the chain and returns one line per exception in the form
    ``ExceptionType: message``, joined with ``  caused by: `` separators.
    The original (root) cause appears last, which is usually the actionable line.

    Example output:
        ValueError: outer message
          caused by: ModuleNotFoundError: No module named 'foo.bar'
    """
    parts: list[str] = []
    current: BaseException | None = exception
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(f"{type(current).__name__}: {current}")
        current = current.__cause__ or current.__context__
    return "\n  caused by: ".join(parts)


def format_exception_traceback(exception: BaseException) -> str:
    """Format an exception with full frames, including chained causes."""
    return "".join(traceback.format_exception(exception)).rstrip()
