import threading
import time
from collections.abc import Callable

from nld.docs.state.models import DocsLiveState

DEFAULT_STATE_TTL_SECONDS: float = 60.0

StateCollector = Callable[[], DocsLiveState]


class CachedStateProvider:
    """Serves the live state from a short-lived cache.

    Collecting the state opens every backend the project declares, which is
    a full scan each time; two tabs polling the page would serialise those
    scans behind the lock. The cache answers repeats within ``ttl_seconds``
    with the same document, and ``refresh=True`` forces a new collection.
    """

    def __init__(
        self,
        collector: StateCollector,
        ttl_seconds: float = DEFAULT_STATE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.collector = collector
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._lock = threading.Lock()
        self._cached: DocsLiveState | None = None
        self._cached_at: float | None = None

    @property
    def cached_state(self) -> DocsLiveState | None:
        """The last collected state, None before the first collection."""
        return self._cached

    def get(
        self,
        refresh: bool = False,
    ) -> DocsLiveState:
        """Return the cached state, collecting when stale or when asked to."""
        with self._lock:
            now = self.clock()
            if (
                not refresh
                and self._cached is not None
                and self._cached_at is not None
                and now - self._cached_at < self.ttl_seconds
            ):
                return self._cached
            self._cached = self.collector()
            self._cached_at = self.clock()
            return self._cached

    def __call__(self) -> DocsLiveState:
        """Allow the provider to stand where a plain collector callable is expected."""
        return self.get()
