"""
ROTATING PROXY GATEWAY — SOCKS5 Proxy Server
Auto-rotating SOCKS5 proxy that uses the Rotator for upstream selection.
"""
import asyncio
import logging
import struct

from .rotator import Rotator

logger = logging.getLogger("gateway.socks5")

SOCKS_VERSION = 0x05
NO_AUTH = 0x00
USER_PASS_AUTH = 0x02
CMD_CONNECT = 0x01
ATYP_IPV4 = 0x01
ATYP_DOMAIN = 0x03
ATYP_IPV6 = 0x04
REP_SUCCESS = 0x00
REP_GENERAL_FAILURE = 0x01
REP_HOST_UNREACHABLE = 0x04


class SOCKS5ProxyServer:
    """SOCKS5 proxy that rotates upstream proxies automatically."""

    def __init__(
        self,
        rotator: Rotator,
        host: str = "0.0.0.0",
        port: int = 32002,
        username: str = "",
        password: str = "",
    ):
        self.rotator = rotator
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self._server = None

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        logger.info(f"SOCKS5 proxy listening on {self.host}:{self.port}")

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        peer = writer.get_extra_info("peername")
        
        # Auto-detect protocol: peek first byte
        try:
            # Read first byte without consuming (peek)
            first_byte = await asyncio.wait_for(reader.read(1), timeout=5)
        except Exception:
            writer.close()
            return
        
        if not first_byte:
            writer.close()
            return
        
        version = first_byte[0]
        
        if version == 0x05:
            # SOCKS5 — continue handshake (already consumed 1 byte, need to read rest)
            try:
                # Read remaining handshake bytes
                nmethods_byte = await asyncio.wait_for(reader.readexactly(1), timeout=5)
                nmethods = nmethods_byte[0]
                methods = await asyncio.wait_for(reader.readexactly(nmethods), timeout=5)
                
                if self.username:
                    if 0x02 not in methods:
                        writer.write(bytes([0x05, 0xFF]))
                        await writer.drain()
                        raise RuntimeError("No acceptable auth method")
                    writer.write(bytes([0x05, 0x02]))
                    await writer.drain()
                    await self._socks_auth_userpass(reader, writer)
                else:
                    writer.write(bytes([0x05, 0x00]))
                    await writer.drain()
                
                target_host, target_port = await self._socks_request(reader, writer)
                logger.debug(f"[{peer}] SOCKS5 → {target_host}:{target_port}")
                await self._socks_connect(writer, target_host, target_port, reader)
            except Exception as e:
                logger.debug(f"[{peer}] SOCKS5 error: {e}")
        else:
            # HTTP — redirect to HTTP handler
            logger.debug(f"[{peer}] HTTP detected (byte={version}), forwarding...")
            await self._handle_http(reader, writer, first_byte)
        
        try:
            writer.close()
        except Exception:
            pass

    async def _socks_handshake(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        """Handle SOCKS5 handshake with optional username/password auth."""
        data = await asyncio.wait_for(reader.readexactly(2), timeout=10)
        version, nmethods = data[0], data[1]
        if version != SOCKS_VERSION:
            raise RuntimeError(f"Bad SOCKS version: {version}")

        # Read supported auth methods
        methods = await asyncio.wait_for(reader.readexactly(nmethods), timeout=5)

        if self.username:
            # Require username/password auth
            if USER_PASS_AUTH not in methods:
                writer.write(bytes([SOCKS_VERSION, 0xFF]))  # No acceptable methods
                await writer.drain()
                raise RuntimeError("Client doesn't support username/password auth")
            writer.write(bytes([SOCKS_VERSION, USER_PASS_AUTH]))
            await writer.drain()

            # Handle username/password sub-negotiation (RFC 1929)
            sub_ver = await asyncio.wait_for(reader.readexactly(1), timeout=5)
            if sub_ver[0] != 0x01:
                raise RuntimeError("Bad username/password version")
            ulen = await asyncio.wait_for(reader.readexactly(1), timeout=5)
            uname = await asyncio.wait_for(reader.readexactly(ulen[0]), timeout=5)
            plen = await asyncio.wait_for(reader.readexactly(1), timeout=5)
            pwd = await asyncio.wait_for(reader.readexactly(plen[0]), timeout=5)

            if uname.decode() != self.username or pwd.decode() != self.password:
                writer.write(bytes([0x01, 0x01]))  # Auth failed
                await writer.drain()
                raise RuntimeError("SOCKS5 auth failed: bad username/password")
            writer.write(bytes([0x01, 0x00]))  # Auth success
            await writer.drain()
        else:
            # No auth
            writer.write(bytes([SOCKS_VERSION, NO_AUTH]))
            await writer.drain()

    async def _socks_auth_userpass(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        """Handle SOCKS5 username/password sub-negotiation (RFC 1929)."""
        sub_ver = await asyncio.wait_for(reader.readexactly(1), timeout=5)
        if sub_ver[0] != 0x01:
            raise RuntimeError("Bad username/password version")
        ulen = await asyncio.wait_for(reader.readexactly(1), timeout=5)
        uname = await asyncio.wait_for(reader.readexactly(ulen[0]), timeout=5)
        plen = await asyncio.wait_for(reader.readexactly(1), timeout=5)
        pwd = await asyncio.wait_for(reader.readexactly(plen[0]), timeout=5)
        if uname.decode() != self.username or pwd.decode() != self.password:
            writer.write(bytes([0x01, 0x01]))  # Auth failed
            await writer.drain()
            raise RuntimeError("SOCKS5 auth failed: bad username/password")
        writer.write(bytes([0x01, 0x00]))  # Auth success
        await writer.drain()

    async def _handle_http(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
        first_byte: bytes
    ):
        """Handle HTTP proxy request that came to SOCKS5 port (auto-detected)."""
        import base64 as _b64
        # Read rest of first line
        first_line_bytes = first_byte + await asyncio.wait_for(
            reader.readline(), timeout=10
        )
        first_line = first_line_bytes.decode("utf-8", errors="replace").strip()
        if not first_line:
            writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            await writer.drain()
            return

        parts = first_line.split()
        if len(parts) < 3:
            writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            await writer.drain()
            return

        method = parts[0].upper()

        # Read headers
        headers = {}
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=10)
            if line == b"\r\n" or line == b"\n" or not line:
                break
            line_str = line.decode("utf-8", errors="replace").strip()
            if ":" in line_str:
                k, v = line_str.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        # HTTP proxy auth check
        if self.username:
            auth_header = headers.get("proxy-authorization", "")
            if not auth_header.startswith("Basic "):
                writer.write(b"HTTP/1.1 407 Proxy Authentication Required\r\n")
                writer.write(b"Proxy-Authenticate: Basic realm=\"BREACH\"\r\n\r\n")
                await writer.drain()
                return
            try:
                decoded = _b64.b64decode(auth_header[6:]).decode("utf-8")
                user, _, pwd = decoded.partition(":")
                if user != self.username or pwd != self.password:
                    writer.write(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
                    await writer.drain()
                    return
            except Exception:
                writer.write(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
                await writer.drain()
                return

        if method == "CONNECT":
            target = parts[1]
            if ":" in target:
                host, port_str = target.rsplit(":", 1)
                try: port = int(port_str)
                except ValueError: port = 443
            else:
                host, port = target, 443

            try:
                remote_reader, remote_writer, _ = await self.rotator.connect(host, port)
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()
                await self._relay(reader, writer, remote_reader, remote_writer)
            except Exception:
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                await writer.drain()
        else:
            # Regular HTTP — forward through upstream proxy
            proxy = None
            try:
                proxy = await self.rotator.pool.get_next()
                remote_reader, remote_writer = await asyncio.wait_for(
                    asyncio.open_connection(proxy.host, proxy.port),
                    timeout=self.rotator.connect_timeout,
                )
                try:
                    remote_writer.write(first_line_bytes + b"\r\n")
                    for k, v in headers.items():
                        remote_writer.write(f"{k}: {v}\r\n".encode())
                    remote_writer.write(b"\r\n")
                    await remote_writer.drain()
                    await self._relay(remote_reader, remote_writer, reader, writer)
                    self.rotator.pool.mark_alive(proxy)
                except Exception:
                    remote_writer.close()
                    raise
            except Exception:
                self.rotator.pool.mark_dead(proxy) if 'proxy' in dir() else None
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                await writer.drain()

    async def _socks_request(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        """Parse SOCKS5 CONNECT request."""
        data = await asyncio.wait_for(reader.readexactly(4), timeout=10)
        version, cmd, reserved, atyp = data[0], data[1], data[2], data[3]

        if version != SOCKS_VERSION:
            raise RuntimeError(f"Bad SOCKS version in request: {version}")
        if cmd != CMD_CONNECT:
            raise RuntimeError(f"Unsupported SOCKS command: {cmd}")

        target_host = None
        target_port = None

        if atyp == ATYP_IPV4:
            addr_data = await asyncio.wait_for(reader.readexactly(4), timeout=5)
            target_host = ".".join(str(b) for b in addr_data)

        elif atyp == ATYP_DOMAIN:
            length_data = await asyncio.wait_for(reader.readexactly(1), timeout=5)
            domain_len = length_data[0]
            domain_data = await asyncio.wait_for(
                reader.readexactly(domain_len), timeout=5
            )
            target_host = domain_data.decode("ascii", errors="replace")

        elif atyp == ATYP_IPV6:
            addr_data = await asyncio.wait_for(reader.readexactly(16), timeout=5)
            # Convert to IPv6 string (simplified)
            parts = [f"{addr_data[i]:02x}{addr_data[i+1]:02x}" for i in range(0, 16, 2)]
            target_host = ":".join(parts)

        else:
            raise RuntimeError(f"Unsupported address type: {atyp}")

        port_data = await asyncio.wait_for(reader.readexactly(2), timeout=5)
        target_port = struct.unpack("!H", port_data)[0]

        return target_host, target_port

    async def _socks_connect(
        self,
        client_writer: asyncio.StreamWriter,
        target_host: str,
        target_port: int,
        client_reader: asyncio.StreamReader,
    ):
        """Connect to target through rotating proxy and relay."""
        try:
            remote_reader, remote_writer, proxy_used = await self.rotator.connect(
                target_host, target_port
            )

            # Send success response with a dummy bind address
            bind_addr = b"\x00\x00\x00\x00"  # 0.0.0.0
            response = (
                bytes([SOCKS_VERSION, REP_SUCCESS, 0x00, ATYP_IPV4])
                + bind_addr
                + struct.pack("!H", 0)
            )
            client_writer.write(response)
            await client_writer.drain()

            # Relay bytes
            await self._relay(client_reader, client_writer, remote_reader, remote_writer)

        except Exception as e:
            logger.debug(f"SOCKS5 connect failed to {target_host}:{target_port}: {e}")
            # Send failure response
            response = (
                bytes([SOCKS_VERSION, REP_HOST_UNREACHABLE, 0x00, ATYP_IPV4])
                + b"\x00\x00\x00\x00"
                + struct.pack("!H", 0)
            )
            client_writer.write(response)
            await client_writer.drain()

    async def _relay(
        self,
        reader_a: asyncio.StreamReader,
        writer_a: asyncio.StreamWriter,
        reader_b: asyncio.StreamReader,
        writer_b: asyncio.StreamWriter,
    ):
        """Bidirectional relay."""

        async def _pipe(src, dst, name):
            try:
                while True:
                    data = await asyncio.wait_for(src.read(8192), timeout=120)
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
