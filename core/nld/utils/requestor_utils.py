import getpass


def resolve_default_requestor() -> str:
    """Return the current OS user, or "unknown" when it cannot be read."""
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"
