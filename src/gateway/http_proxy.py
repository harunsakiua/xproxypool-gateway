"""
ROTATING PROXY GATEWAY — HTTP Proxy Server
Handles HTTP forward proxy and CONNECT tunnel (HTTPS) with rotation.
"""
import asyncio
import base64
import logging
from urllib.parse import urlparse

from .rotator import Rotator

logger = logging.getLogger("gateway.http")


class HTTPProxyServer:
    """HTTP forward proxy that auto-rotates upstream proxies."""

    def __init__(
        self,
        rotator: Rotator,
        host: str = "0.0.0.0",
        port: int = 32001,
        username: str = "",
        password: str = "",
    ):
        self.rotator = rotator
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self._server = None

    @property
    def requires_auth(self) -> bool:
        return bool(self.username)

    def _check_auth(self, headers: dict) -> bool:
        """Validate Proxy-Authorization: Basic <base64(user:pass)> header."""
        auth_header = headers.get("proxy-authorization", "")
        if not auth_header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            user, _, pwd = decoded.partition(":")
            return user == self.username and pwd == self.password
        except Exception:
            return False

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        logger.info(f"HTTP proxy listening on {self.host}:{self.port}")

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_client(
        self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ):
        try:
            await self._handle_request(client_reader, client_writer)
        except Exception:
            pass
        finally:
            try:
                client_writer.close()
            except Exception:
                pass

    async def _handle_request(
        self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ):
        """Parse the first line to determine CONNECT vs regular HTTP."""
        # Read first line
        request_line = await asyncio.wait_for(
            client_reader.readline(), timeout=30
        )
        if not request_line:
            return

        request_str = request_line.decode("utf-8", errors="replace").strip()
        if not request_str:
            return

        parts = request_str.split()
        if len(parts) < 3:
            return

        method, url_or_path, version = parts[0], parts[1], parts[2]

        if method.upper() == "CONNECT":
            # Read headers to check auth
            headers = {}
            while True:
                line = await asyncio.wait_for(client_reader.readline(), timeout=10)
                if line == b"\r\n" or line == b"\n" or not line:
                    break
                line_str = line.decode("utf-8", errors="replace").strip()
                if ":" in line_str:
                    k, v = line_str.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            # Check auth
            if self.requires_auth and not self._check_auth(headers):
                client_writer.write(b"HTTP/1.1 407 Proxy Authentication Required\r\n")
                client_writer.write(b"Proxy-Authenticate: Basic realm=\"BREACH Gateway\"\r\n")
                client_writer.write(b"Content-Length: 0\r\n\r\n")
                await client_writer.drain()
                return

            # Handle CONNECT tunnel
            await self._handle_connect(
                client_reader, client_writer, url_or_path, version
            )
        else:
            # Regular HTTP forward — parse destination
            await self._handle_http_forward(
                client_reader, client_writer, method, url_or_path, version,
                request_str
            )

    async def _handle_connect(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        target: str,  # host:port
        version: str,
    ):
        """Handle CONNECT tunnel (HTTPS)."""
        # Parse host:port
        if ":" in target:
            host, port_str = target.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                port = 443
        else:
            host = target
            port = 443

        # Consume remaining headers
        while True:
            line = await asyncio.wait_for(client_reader.readline(), timeout=10)
            if line == b"\r\n" or line == b"\n" or not line:
                break

        # Connect through rotating proxy
        try:
            remote_reader, remote_writer, proxy_used = await self.rotator.connect(
                host, port
            )
            client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await client_writer.drain()

            # Bidirectional relay
            await self._relay(client_reader, client_writer, remote_reader, remote_writer)
        except Exception as e:
            logger.debug(f"CONNECT failed to {target}: {e}")
            client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            await client_writer.drain()

    async def _handle_http_forward(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        method: str,
        url: str,
        version: str,
        first_line: str,
    ):
        """Handle regular HTTP forward request — send directly through upstream proxy."""
        parsed = urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port or 80

        if not host:
            client_writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            await client_writer.drain()
            return

        # Read all headers
        headers_data = first_line + "\r\n"
        while True:
            line = await asyncio.wait_for(client_reader.readline(), timeout=10)
            headers_data += line.decode("utf-8", errors="replace")
            if line == b"\r\n" or line == b"\n" or not line:
                break

        # Send through upstream HTTP proxy (not CONNECT — direct forward)
        proxy = None
        try:
            proxy = await self.rotator.pool.get_next()
            logger.debug(f"HTTP fwd via {proxy.url} → {host}:{port}")
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(proxy.host, proxy.port),
                timeout=self.rotator.connect_timeout,
            )

            try:
                # Send request with absolute URL (HTTP proxy standard)
                request_bytes = headers_data.encode()
                writer.write(request_bytes)
                await writer.drain()

                # Read body if present
                if "content-length" in headers_data.lower():
                    import re
                    match = re.search(r"Content-Length:\s*(\d+)", headers_data, re.IGNORECASE)
                    if match:
                        body_len = int(match.group(1))
                        body = await asyncio.wait_for(
                            client_reader.readexactly(body_len), timeout=30
                        )
                        writer.write(body)
                        await writer.drain()

                # Relay response back
                await self._relay(reader, writer, client_reader, client_writer)
                self.rotator.pool.mark_alive(proxy)

            except Exception:
                writer.close()
                raise

        except Exception as e:
            self.rotator.pool.mark_dead(proxy)
            logger.debug(f"HTTP fwd failed to {host}: {e}")
            try:
                client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                await client_writer.drain()
            except Exception:
                pass

    async def _relay(
        self,
        reader_a: asyncio.StreamReader,
        writer_a: asyncio.StreamWriter,
        reader_b: asyncio.StreamReader,
        writer_b: asyncio.StreamWriter,
    ):
        """Bidirectional relay between two pairs."""

        async def _pipe(src, dst, name):
            try:
                while True:
                    data = await asyncio.wait_for(src.read(8192), timeout=60)
                    if not data:
                        break
                    dst.write(data)
                    await dst.drain()
            except Exception:
                pass
            finally:
                try:
                    dst.close()
                except Exception:
                    pass

        await asyncio.gather(
            _pipe(reader_a, writer_b, "out"),
            _pipe(reader_b, writer_a, "in"),
        )
