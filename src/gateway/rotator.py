"""
ROTATING PROXY GATEWAY — Rotator + Failover Engine
"""
import asyncio
import logging
import time
from typing import Optional, Tuple

from .pool import CachedProxy, PoolManager

logger = logging.getLogger("gateway.rotator")


class Rotator:
    """Handles proxy rotation with automatic failover."""

    def __init__(
        self,
        pool: PoolManager,
        max_retries: int = 3,
        connect_timeout: int = 8,
    ):
        self.pool = pool
        self.max_retries = max_retries
        self.connect_timeout = connect_timeout

    async def connect(
        self, target_host: str, target_port: int
    ) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter, CachedProxy]:
        """
        Connect to target through a rotating proxy with failover.

        Returns (reader, writer, proxy_used).
        On total failure, raises the last exception.
        """
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                proxy = await self.pool.get_next()
            except RuntimeError:
                raise RuntimeError("No proxies available after pool exhaustion")

            try:
                logger.debug(
                    f"[attempt {attempt+1}/{self.max_retries+1}] "
                    f"→ {target_host}:{target_port} via {proxy.url} "
                    f"(score={proxy.score}, failures={proxy.failures})"
                )
                reader, writer = await self._connect_via_proxy(
                    proxy, target_host, target_port
                )
                self.pool.mark_alive(proxy)
                logger.debug(f"[attempt {attempt+1}] ✓ {proxy.url}")
                return reader, writer, proxy
            except Exception as e:
                self.pool.mark_dead(proxy)
                logger.debug(
                    f"[attempt {attempt+1}] ✗ {proxy.url}: {e} "
                    f"(failures now={proxy.failures+1})"
                )
                last_error = e
                continue

        raise RuntimeError(
            f"All {self.max_retries + 1} proxy attempts failed. "
            f"Last error: {last_error}"
        )

    async def _connect_via_proxy(
        self, proxy: CachedProxy, target_host: str, target_port: int
    ) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """
        Connect to target through an HTTP proxy using CONNECT tunnel.
        Also handles SOCKS5 via aiohttp-socks.
        """
        if proxy.protocol in ("socks4", "socks5"):
            return await self._connect_via_socks(proxy, target_host, target_port)
        else:
            return await self._connect_via_http_connect(
                proxy, target_host, target_port
            )

    async def _connect_via_socks(
        self, proxy: CachedProxy, target_host: str, target_port: int
    ) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Connect through SOCKS5 proxy."""
        import struct
        import socket

        # Connect to SOCKS5 proxy
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(proxy.host, proxy.port),
            timeout=self.connect_timeout,
        )

        try:
            # SOCKS5 handshake
            writer.write(b"\x05\x01\x00")  # version 5, 1 method, no auth
            await writer.drain()

            resp = await asyncio.wait_for(reader.readexactly(2), timeout=5)
            if resp != b"\x05\x00":
                raise RuntimeError(f"SOCKS5 upstream rejected handshake: {resp.hex()}")

            # SOCKS5 CONNECT request
            addr_bytes = target_host.encode("ascii", errors="replace")
            if len(addr_bytes) > 255:
                addr_bytes = addr_bytes[:255]

            req = (
                b"\x05\x01\x00\x03"  # version, CONNECT, reserved, domain type
                + bytes([len(addr_bytes)])
                + addr_bytes
                + struct.pack("!H", target_port)
            )
            writer.write(req)
            await writer.drain()

            # Read response
            resp = await asyncio.wait_for(reader.read(10), timeout=5)
            if len(resp) < 10 or resp[1] != 0x00:
                status = resp[1] if len(resp) > 1 else -1
                raise RuntimeError(f"SOCKS5 upstream CONNECT rejected: status={status}")

            return reader, writer

        except Exception:
            writer.close()
            raise

    async def _connect_via_http_connect(
        self, proxy: CachedProxy, target_host: str, target_port: int
    ) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Connect through HTTP proxy using CONNECT tunnel."""
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(proxy.host, proxy.port),
            timeout=self.connect_timeout,
        )

        try:
            # HTTP CONNECT request
            connect_req = (
                f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n"
                f"Host: {target_host}:{target_port}\r\n"
                f"User-Agent: BREACH-Gateway/1.0\r\n"
                f"Proxy-Connection: Keep-Alive\r\n"
                f"\r\n"
            )
            writer.write(connect_req.encode())
            await writer.drain()

            # Read HTTP response
            response = await asyncio.wait_for(reader.readline(), timeout=5)
            status_line = response.decode("utf-8", errors="replace").strip()

            if "200" not in status_line:
                # Read and discard remaining headers
                while True:
                    line = await asyncio.wait_for(reader.readline(), timeout=3)
                    if line == b"\r\n" or line == b"\n" or not line:
                        break
                raise RuntimeError(f"HTTP CONNECT rejected: {status_line}")

            # Read remaining headers
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=3)
                if line == b"\r\n" or line == b"\n" or not line:
                    break

            return reader, writer

        except Exception:
            writer.close()
            raise
