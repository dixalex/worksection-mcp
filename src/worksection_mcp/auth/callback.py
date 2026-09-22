"""HTTP callback server for OAuth2 authorization flow."""

import asyncio
import logging
import re
import socket
import ssl
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

_REDACT_CODE_RE = re.compile(r"code=[^&\s]+")

type CallbackHandlerFn = Callable[[str | None, str | None], None]


class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler for OAuth2 callback."""

    callback_received: CallbackHandlerFn | None = None
    success_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Authorization Successful</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            }
            .container {
                text-align: center;
                background: white;
                padding: 40px 60px;
                border-radius: 10px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            }
            h1 { color: #28a745; margin-bottom: 10px; }
            p { color: #666; }
            .checkmark { font-size: 48px; margin-bottom: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="checkmark">✓</div>
            <h1>Authorization Successful!</h1>
            <p>You can close this window and return to the application.</p>
        </div>
    </body>
    </html>
    """

    error_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Authorization Failed</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background: linear-gradient(135deg, #ff6b6b 0%, #ee5a5a 100%);
            }
            .container {
                text-align: center;
                background: white;
                padding: 40px 60px;
                border-radius: 10px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            }
            h1 { color: #dc3545; margin-bottom: 10px; }
            p { color: #666; }
            .error-icon { font-size: 48px; margin-bottom: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="error-icon">✗</div>
            <h1>Authorization Failed</h1>
            <p>Error: {error}</p>
            <p>Please try again.</p>
        </div>
    </body>
    </html>
    """

    def log_message(self, *args: object, **kwargs: object) -> None:
        """Override to use Python logging instead of stderr."""
        fmt = kwargs.get("format")
        fmt_args = args

        if fmt is None and args:
            fmt = args[0]
            fmt_args = args[1:]

        if fmt is None:
            logger.debug("Callback server")
            return

        try:
            message = str(fmt) % fmt_args if fmt_args else str(fmt)
        except TypeError, ValueError:
            message = str(fmt)

        safe_message = _REDACT_CODE_RE.sub("code=[REDACTED]", message)
        logger.debug("Callback server: %s", safe_message)

    def do_GET(self):
        """Handle GET request (OAuth callback)."""
        parsed = urlparse(self.path)

        if parsed.path != "/oauth/callback":
            self.send_error(404, "Not Found")
            return

        query_params = parse_qs(parsed.query)

        # Check for error
        if "error" in query_params:
            error = query_params["error"][0]
            error_desc = query_params.get("error_description", ["Unknown error"])[0]
            logger.error(f"OAuth error: {error} - {error_desc}")

            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            # Avoid str.format() on CSS-heavy HTML, which contains many braces.
            self.wfile.write(self.error_html.replace("{error}", error_desc).encode())

            if self.callback_received:
                self.callback_received(None, f"{error}: {error_desc}")
            return

        # Get authorization code
        if "code" not in query_params:
            self.send_error(400, "Missing authorization code")
            return

        code = query_params["code"][0]
        state = query_params.get("state", [None])[0]

        logger.info("Authorization code received")

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(self.success_html.encode())

        if self.callback_received:
            self.callback_received(code, state)


class CallbackServer:
    """Temporary HTTP/HTTPS server for OAuth2 callback."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8080,
        ssl_context: ssl.SSLContext | None = None,
    ):
        """Initialize callback server.

        Args:
            host: Host to bind to
            port: Port to listen on
            ssl_context: SSL context for HTTPS (None for HTTP)
        """
        self.host = host
        self.port = port
        self.ssl_context = ssl_context
        self._server: HTTPServer | None = None
        self._thread: Thread | None = None
        self._code_future: asyncio.Future[tuple[str, str | None]] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _handle_callback(self, code: str | None, state_or_error: str | None):
        """Handle callback from request handler."""
        if self._code_future and not self._code_future.done() and self._loop:
            if code:
                # Success - set the code
                self._loop.call_soon_threadsafe(
                    self._code_future.set_result, (code, state_or_error)
                )
            else:
                # Error - set exception
                self._loop.call_soon_threadsafe(
                    self._code_future.set_exception,
                    Exception(f"OAuth error: {state_or_error}"),
                )

    def start(self) -> None:
        """Start the callback server in a background thread."""
        if self._server:
            return

        # Configure handler with callback
        CallbackHandler.callback_received = self._handle_callback

        server_cls = HTTPServer
        if ":" in self.host:

            class _HTTPServerV6(HTTPServer):
                address_family = socket.AF_INET6

            server_cls = _HTTPServerV6

        self._server = server_cls((self.host, self.port), CallbackHandler)

        # Wrap socket with SSL if context provided
        if self.ssl_context:
            self._server.socket = self.ssl_context.wrap_socket(
                self._server.socket,
                server_side=True,
            )

        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        protocol = "https" if self.ssl_context else "http"
        logger.info(f"Callback server started at {protocol}://{self.host}:{self.port}")

    def stop(self) -> None:
        """Stop the callback server."""
        if self._server:
            self._server.shutdown()
            self._server = None
            self._thread = None
            logger.info("Callback server stopped")

    async def wait_for_callback(self, timeout_seconds: float = 300) -> tuple[str, str | None]:
        """Wait for OAuth callback.

        Args:
            timeout_seconds: Maximum time to wait in seconds

        Returns:
            Tuple of (authorization_code, state)

        Raises:
            asyncio.TimeoutError: If callback not received in time
            Exception: If OAuth error occurs
        """
        # Store event loop reference for cross-thread callback
        self._loop = asyncio.get_running_loop()
        self._code_future = self._loop.create_future()

        try:
            return await asyncio.wait_for(self._code_future, timeout=timeout_seconds)
        finally:
            self._code_future = None
            self._loop = None

    @property
    def callback_url(self) -> str:
        """Get the full callback URL."""
        protocol = "https" if self.ssl_context else "http"
        return f"{protocol}://{self.host}:{self.port}/oauth/callback"
