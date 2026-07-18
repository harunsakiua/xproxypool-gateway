import re
from abc import ABC, abstractmethod
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup

from proxy_pool.schemas.proxy import Proxy
from proxy_pool.utils.logger import logger

_IP_PORT_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})[:\s]+(\d{2,5})")

# Domains that are blocked in mainland China — skip direct attempt, use proxy directly
_PROXY_ONLY_HOSTS = {
    "raw.githubusercontent.com",
    "github.com",
    "cdn.jsdelivr.net",
}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

class BaseFetcher(ABC):
    source: str = ""
    timeout: int = 15

    @abstractmethod
    async def fetch(self) -> list[Proxy]:
        """Fetch proxies from the source. Must be implemented by subclasses."""

    # ------------------------------------------------------------------ #
    # HTTP helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _needs_proxy(url: str) -> bool:
        """Return True if the URL's host is known to be blocked in mainland China."""
        try:
            from urllib.parse import urlparse
            host = urlparse(url).hostname or ""
            return host in _PROXY_ONLY_HOSTS
        except Exception:
            return False

    @staticmethod
    def _connector(force_close: bool = True) -> aiohttp.TCPConnector:
        """
        Create a TCPConnector with force_close=True so the TCP socket is
        released immediately after each response instead of being returned
        to the pool — prevents CLOSE_WAIT accumulation on the host proxy.
        """
        return aiohttp.TCPConnector(force_close=force_close, ssl=False)

    async def get_html(self, url: str, headers: Optional[dict] = None) -> str:
        merged = {**DEFAULT_HEADERS, **(headers or {})}
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        content: bytes | None = None
        charset: str | None = None

        # Skip direct attempt for known-blocked hosts
        if not self._needs_proxy(url):
            connector = self._connector()
            try:
                async with aiohttp.ClientSession(
                    connector=connector, connector_owner=False, trust_env=False
                ) as session:
                    async with session.get(url, headers=merged, timeout=timeout, ssl=False) as resp:
                        content = await resp.read()
                        charset = resp.charset
            except Exception:
                pass
            finally:
                await connector.close()

        # Fallback (or primary for blocked hosts): system proxy
        if content is None:
            connector = self._connector()
            try:
                async with aiohttp.ClientSession(
                    connector=connector, connector_owner=False, trust_env=True
                ) as session:
                    async with session.get(url, headers=merged, timeout=timeout, ssl=False) as resp:
                        content = await resp.read()
                        charset = resp.charset
                        logger.debug("get_html via proxy: {}", url)
            except Exception as exc:
                logger.warning("get_html failed for {}: {}", url, exc)
            finally:
                await connector.close()

        if content is None:
            return ""
        for enc in filter(None, [charset, "utf-8", "gb18030", "latin-1"]):
            try:
                return content.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return content.decode("utf-8", errors="ignore")

    async def get_json(self, url: str, headers: Optional[dict] = None) -> dict | list:
        merged = {**DEFAULT_HEADERS, **(headers or {})}
        timeout = aiohttp.ClientTimeout(total=self.timeout)

        # Skip direct attempt for known-blocked hosts
        if not self._needs_proxy(url):
            connector = self._connector()
            try:
                async with aiohttp.ClientSession(
                    connector=connector, connector_owner=False, trust_env=False
                ) as session:
                    async with session.get(url, headers=merged, timeout=timeout, ssl=False) as resp:
                        return await resp.json(content_type=None)
            except Exception:
                pass
            finally:
                await connector.close()

        # Fallback (or primary for blocked hosts): system proxy
        connector = self._connector()
        try:
            async with aiohttp.ClientSession(
                connector=connector, connector_owner=False, trust_env=True
            ) as session:
                async with session.get(url, headers=merged, timeout=timeout, ssl=False) as resp:
                    logger.debug("get_json via proxy: {}", url)
                    return await resp.json(content_type=None)
        except Exception as exc:
            logger.warning("get_json failed for {}: {}", url, exc)
            return {}
        finally:
            await connector.close()

    # ------------------------------------------------------------------ #
    # Parsing helpers
    # ------------------------------------------------------------------ #

    def _parse_text(self, text: str, protocol: str = "http") -> list[Proxy]:
        """Parse raw text with lines like 'ip:port' or 'ip port'."""
        proxies = []
        for m in _IP_PORT_RE.finditer(text):
            try:
                proxies.append(
                    Proxy(host=m.group(1), port=int(m.group(2)), protocol=protocol, source=self.source)
                )
            except Exception:
                pass
        return proxies

    def _parse_table(self, html: str, protocol: str = "http") -> list[Proxy]:
        """Parse HTML tables where first column = IP, second = port."""
        soup = BeautifulSoup(html, "lxml")
        proxies = []
        for tr in soup.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            ip = tds[0].get_text(strip=True)
            port_text = tds[1].get_text(strip=True)
            if not re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", ip):
                continue
            try:
                proxies.append(
                    Proxy(host=ip, port=int(port_text), protocol=protocol, source=self.source)
                )
            except Exception:
                pass
        return proxies
