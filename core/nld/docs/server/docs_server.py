import json
import os
from collections.abc import Callable
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from nld.docs.models import ProjectSnapshot
from nld.docs.state.cache import CachedStateProvider
from nld.docs.state.errors import categorise_backend_error

API_SNAPSHOT_PATH: str = "/api/snapshot"
API_STATE_PATH: str = "/api/state"
API_HEALTH_PATH: str = "/api/health"

REFRESH_QUERY_PARAMETER: str = "refresh"

DEFAULT_HOST: str = "127.0.0.1"
DEFAULT_PORT: int = 8765

LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})

RouteHandler = Callable[["DocsRequestHandler", dict[str, list[str]]], None]


def is_loopback_host(host: str) -> bool:
    """Whether a bind address keeps the server on this machine only."""
    return host in LOOPBACK_HOSTS


class DocsRequestHandler(SimpleHTTPRequestHandler):
    """Serves the generated site plus the read-only docs API.

    The state endpoint is answered on demand rather than at start-up so the
    server comes up even when no environment is reachable, which is the
    normal case on a laptop.
    """

    def __init__(
        self,
        *args: Any,
        site_folder_path: str,
        snapshot_json: str,
        state_provider: CachedStateProvider | None,
        **kwargs: Any,
    ) -> None:
        self.site_folder_path = site_folder_path
        self.snapshot_json = snapshot_json
        self.state_provider = state_provider
        super().__init__(
            *args,
            directory=site_folder_path,
            **kwargs,
        )

    def do_GET(self) -> None:  # noqa: N802 - imposed by BaseHTTPRequestHandler
        """Answer the API paths, and fall back to the static site."""
        parsed = urlsplit(self.path)
        route = API_ROUTES.get(parsed.path)
        if route is None:
            super().do_GET()
            return
        route(self, parse_qs(parsed.query))

    def log_message(
        self,
        format: str,  # noqa: A002 - imposed by BaseHTTPRequestHandler
        *args: Any,
    ) -> None:
        """Silence the default per-request logging on stderr."""

    def _write_health(
        self,
        query: dict[str, list[str]],
    ) -> None:
        """Say the server is up and whether it can answer for the live state."""
        self._write_json(
            payload={
                "status": "ok",
                "state_enabled": self.state_provider is not None,
            },
        )

    def _write_snapshot(
        self,
        query: dict[str, list[str]],
    ) -> None:
        """Serve the snapshot the site was built from."""
        self._write_raw_json(body=self.snapshot_json)

    def _write_state(
        self,
        query: dict[str, list[str]],
    ) -> None:
        """Serve the live state, degrading on any failure.

        ``?refresh=1`` bypasses the cache; the page's refresh button uses it.
        """
        if self.state_provider is None:
            self._write_json(
                payload={
                    "available": False,
                    "message": "The live-state layer is disabled for this server.",
                },
            )
            return

        refresh = query.get(REFRESH_QUERY_PARAMETER, ["0"])[0] not in ("", "0", "false")
        try:
            state = self.state_provider.get(refresh=refresh)
            payload = state.model_dump(mode="json")
        except Exception as error:  # noqa: BLE001 - the UI shows the category
            payload = {
                "available": False,
                "message": categorise_backend_error(error=error),
            }
        self._write_json(payload=payload)

    def _write_json(
        self,
        payload: dict[str, Any],
    ) -> None:
        """Serialise a payload and write it as a JSON response."""
        self._write_raw_json(
            body=json.dumps(
                payload,
                ensure_ascii=False,
                default=str,
            ),
        )

    def _write_raw_json(
        self,
        body: str,
    ) -> None:
        """Write an already serialised JSON body."""
        encoded = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)


API_ROUTES: dict[str, RouteHandler] = {
    API_HEALTH_PATH: DocsRequestHandler._write_health,
    API_SNAPSHOT_PATH: DocsRequestHandler._write_snapshot,
    API_STATE_PATH: DocsRequestHandler._write_state,
}


class DocsServer:
    """A local HTTP server for one generated documentation site."""

    def __init__(
        self,
        site_folder_path: str,
        snapshot: ProjectSnapshot,
        state_provider: CachedStateProvider | None = None,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ) -> None:
        self.site_folder_path = site_folder_path
        self.snapshot = snapshot
        self.state_provider = state_provider
        self.host = host
        self.port = port
        self._http_server: ThreadingHTTPServer | None = None

    @property
    def url(self) -> str:
        """The URL the site is reachable at."""
        host, port = self.address
        return f"http://{host}:{port}/"

    @property
    def address(self) -> tuple[str, int]:
        """The bound address, resolved after the socket is open."""
        if self._http_server is None:
            return self.host, self.port
        bound_host, bound_port = self._http_server.server_address[:2]
        return str(bound_host), int(bound_port)

    def create(self) -> ThreadingHTTPServer:
        """Bind the socket and return the underlying HTTP server."""
        if not os.path.isdir(self.site_folder_path):
            raise FileNotFoundError(
                f"The documentation site folder does not exist: {self.site_folder_path}"
            )

        handler = partial(
            DocsRequestHandler,
            site_folder_path=self.site_folder_path,
            snapshot_json=json.dumps(
                self.snapshot.model_dump(mode="json"),
                ensure_ascii=False,
                default=str,
            ),
            state_provider=self.state_provider,
        )
        self._http_server = ThreadingHTTPServer(
            (self.host, self.port),
            handler,
        )
        return self._http_server

    def serve_forever(self) -> None:
        """Serve until the process is interrupted."""
        http_server = self._http_server or self.create()
        try:
            http_server.serve_forever()
        finally:
            http_server.server_close()
            self._http_server = None

    def shutdown(self) -> None:
        """Stop a server started in another thread."""
        if self._http_server is not None:
            self._http_server.shutdown()
            self._http_server.server_close()
            self._http_server = None
