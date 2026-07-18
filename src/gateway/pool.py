"""
ROTATING PROXY GATEWAY — Pool Manager
Fetches from Xproxypool, maintains local cache, handles refill.
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

GATEWAY_USER_AGENT = "BREACH-Gateway/1.0"


@dataclass
class CachedProxy:
    host: str
    port: int
    protocol: str  # http, socks5
    score: int
    ping: int  # ms
    source: str
    url: str  # full URL like http://1.2.3.4:8080 or socks5://1.2.3.4:1080
    failures: int = 0
    last_used: float = 0.0

    @property
    def proxy_url(self) -> str:
        return self.url

    @property
    def alive(self) -> bool:
        return self.failures < 3


class PoolManager:
    """Maintains a local pool of working proxies fetched from Xproxypool."""

    def __init__(
        self,
        api_url: str = "http://localhost:12563",
        pool_name: str = "intl",
        min_score: int = 50,
        max_size: int = 100,
        refill_interval: int = 30,
        min_pool_size: int = 20,
    ):
        self.api_url = api_url.rstrip("/")
        self.pool_name = pool_name
        self.min_score = min_score
        self.max_size = max_size
        self.refill_interval = refill_interval
        self.min_pool_size = min_pool_size

        self._proxies: list[CachedProxy] = []
        self._index: int = 0
        self._lock = asyncio.Lock()
        self._session: Optional[aiohttp.ClientSession] = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    @property
    def size(self) -> int:
        return len([p for p in self._proxies if p.alive])

    async def start(self):
        """Start background refill task."""
        self._session = aiohttp.ClientSession()
        # Initial fill
        await self._refill()
        # Background refill
        asyncio.create_task(self._refill_loop())

    async def stop(self):
        if self._session:
            await self._session.close()

    async def get_next(self) -> CachedProxy:
        """Get next proxy (prefer recently-working ones)."""
        async with self._lock:
            alive = [p for p in self._proxies if p.alive]
            if not alive:
                await self._refill()
                alive = [p for p in self._proxies if p.alive]
                if not alive:
                    raise RuntimeError("No proxies available — pool is empty")

            # Sort: prefer proxies with 0 failures (recently working), then by score
            alive.sort(key=lambda p: (p.failures, -p.score))

            # Pick from top 70% most of the time, random otherwise (explore new proxies)
            import random
            if random.random() < 0.7:
                # Top third
                top_n = max(3, len(alive) // 3)
                proxy = random.choice(alive[:top_n])
            else:
                # Explore rest
                proxy = random.choice(alive)

            proxy.last_used = time.time()
            return proxy

    def mark_dead(self, proxy: CachedProxy):
        """Mark a proxy as failed."""
        proxy.failures += 1
        # Remove if too many failures
        if proxy.failures >= 3:
            try:
                self._proxies.remove(proxy)
            except ValueError:
                pass

    def mark_alive(self, proxy: CachedProxy):
        """Reset failure count on success."""
        proxy.failures = 0

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    async def _refill_loop(self):
        while True:
            await asyncio.sleep(self.refill_interval)
            alive_count = self.size
            if alive_count < self.min_pool_size:
                await self._refill()

    async def _refill(self):
        """Fetch fresh proxies from Xproxypool API."""
        alive_count = self.size
        needed = self.max_size - alive_count
        if needed <= 0:
            return

        # Try to get up to `needed` proxies
        fetched = 0
        max_attempts = needed * 3  # 3:1 ratio since many will be dupes or dead

        for _ in range(max_attempts):
            if fetched >= needed:
                break
            try:
                proxy = await self._fetch_one()
                if proxy and not self._is_duplicate(proxy):
                    async with self._lock:
                        self._proxies.append(proxy)
                    fetched += 1
            except Exception:
                pass

    async def _fetch_one(self) -> Optional[CachedProxy]:
        """Fetch one proxy from Xproxypool GET /get."""
        try:
            async with self._session.get(
                f"{self.api_url}/get",
                params={
                    "pool": self.pool_name,
                    "min_score": self.min_score,
                },
                timeout=aiohttp.ClientTimeout(total=5),
                headers={"User-Agent": GATEWAY_USER_AGENT},
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                host = data.get("host", "")
                port = data.get("port", 0)
                protocol = data.get("protocol", "http")
                score = data.get("score", 0)
                ping = data.get("ping", 0)
                source = data.get("source", "")

                if not host or not port:
                    return None

                # Build URL
                if protocol in ("socks4", "socks5"):
                    proxy_url = f"{protocol}://{host}:{port}"
                else:
                    proxy_url = f"http://{host}:{port}"

                return CachedProxy(
                    host=host,
                    port=port,
                    protocol=protocol,
                    score=score,
                    ping=ping,
                    source=source,
                    url=proxy_url,
                )
        except Exception:
            return None

    def _is_duplicate(self, proxy: CachedProxy) -> bool:
        for p in self._proxies:
            if p.host == proxy.host and p.port == proxy.port:
                return True
        return False
