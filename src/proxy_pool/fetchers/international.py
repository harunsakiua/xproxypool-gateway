"""
International proxy fetchers — 5 sources.
URLs are configured in sources.yml at the project root.
"""

import asyncio
import re

from bs4 import BeautifulSoup

from proxy_pool.fetchers.base import BaseFetcher
from proxy_pool.schemas.proxy import Proxy
from proxy_pool.utils.logger import logger
from proxy_pool.utils.sources import get

class ProxyScrapeFetcher(BaseFetcher):
    source = "proxyscrape"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "proxyscrape")
        if not cfg.get("enabled", True):
            return []
        proxies: list[Proxy] = []
        for protocol, url in cfg.get("urls", {}).items():
            try:
                text = await self.get_html(url)
                proxies.extend(self._parse_text(text, protocol=protocol))
            except Exception as e:
                logger.warning("ProxyScrapeFetcher protocol={} error: {}", protocol, e)
        return proxies

class GeonodeFetcher(BaseFetcher):
    source = "geonode"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "geonode")
        if not cfg.get("enabled", True):
            return []
        proxies: list[Proxy] = []
        url_tpl = cfg.get("url_template", "")
        for page in range(1, cfg.get("pages", 3) + 1):
            url = url_tpl.format(page=page)
            try:
                data = await self.get_json(url)
                for item in data.get("data", []):
                    host = item.get("ip", "")
                    port = item.get("port", 0)
                    protocols = item.get("protocols", ["http"])
                    protocol = protocols[0].lower() if protocols else "http"
                    try:
                        proxies.append(
                            Proxy(host=host, port=int(port), protocol=protocol, source=self.source)
                        )
                    except Exception:
                        pass
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.warning("GeonodeFetcher page={} error: {}", page, e)
        return proxies

class TheSpeedXFetcher(BaseFetcher):
    source = "thespeedx"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "thespeedx")
        if not cfg.get("enabled", True):
            return []
        proxies: list[Proxy] = []
        for protocol, url in cfg.get("urls", {}).items():
            try:
                text = await self.get_html(url)
                proxies.extend(self._parse_text(text, protocol=protocol))
            except Exception as e:
                logger.warning("TheSpeedXFetcher protocol={} error: {}", protocol, e)
        return proxies

class MonosansFetcher(BaseFetcher):
    source = "monosans"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "monosans")
        if not cfg.get("enabled", True):
            return []
        proxies: list[Proxy] = []
        for protocol, url in cfg.get("urls", {}).items():
            try:
                text = await self.get_html(url)
                proxies.extend(self._parse_text(text, protocol=protocol))
            except Exception as e:
                logger.warning("MonosansFetcher protocol={} error: {}", protocol, e)
        return proxies

class OpenProxyListFetcher(BaseFetcher):
    source = "openproxylist"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "openproxylist")
        if not cfg.get("enabled", True):
            return []
        url = cfg.get("url", "")
        try:
            text = await self.get_html(url)
            return self._parse_text(text)
        except Exception as e:
            logger.warning("OpenProxyListFetcher error: {}", e)
            return []

class ProxiflyFetcher(BaseFetcher):
    source = "proxifly"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "proxifly")
        if not cfg.get("enabled", True):
            return []
        proxies: list[Proxy] = []
        for protocol, url in cfg.get("urls", {}).items():
            try:
                text = await self.get_html(url)
                proxies.extend(self._parse_text(text, protocol=protocol))
            except Exception as e:
                logger.warning("ProxiflyFetcher protocol={} error: {}", protocol, e)
        return proxies

class Komutan234Fetcher(BaseFetcher):
    source = "komutan234"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "komutan234")
        if not cfg.get("enabled", True):
            return []
        proxies: list[Proxy] = []
        for protocol, url in cfg.get("urls", {}).items():
            try:
                text = await self.get_html(url)
                proxies.extend(self._parse_text(text, protocol=protocol))
            except Exception as e:
                logger.warning("Komutan234Fetcher protocol={} error: {}", protocol, e)
        return proxies

class ClearProxyFetcher(BaseFetcher):
    source = "clearproxy"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "clearproxy")
        if not cfg.get("enabled", True):
            return []
        proxies: list[Proxy] = []
        for protocol, url in cfg.get("urls", {}).items():
            try:
                text = await self.get_html(url)
                proxies.extend(self._parse_text(text, protocol=protocol))
            except Exception as e:
                logger.warning("ClearProxyFetcher protocol={} error: {}", protocol, e)
        return proxies

class VakhovFetcher(BaseFetcher):
    source = "vakhov"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "vakhov")
        if not cfg.get("enabled", True):
            return []
        proxies: list[Proxy] = []
        for protocol, url in cfg.get("urls", {}).items():
            try:
                text = await self.get_html(url)
                proxies.extend(self._parse_text(text, protocol=protocol))
            except Exception as e:
                logger.warning("VakhovFetcher protocol={} error: {}", protocol, e)
        return proxies

class MuRongPIGFetcher(BaseFetcher):
    source = "murongpig"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "murongpig")
        if not cfg.get("enabled", True):
            return []
        proxies: list[Proxy] = []
        for protocol, url in cfg.get("urls", {}).items():
            try:
                text = await self.get_html(url)
                proxies.extend(self._parse_text(text, protocol=protocol))
            except Exception as e:
                logger.warning("MuRongPIGFetcher protocol={} error: {}", protocol, e)
        return proxies

class VMHeavenFetcher(BaseFetcher):
    source = "vmheaven"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "vmheaven")
        if not cfg.get("enabled", True):
            return []
        proxies: list[Proxy] = []
        for protocol, url in cfg.get("urls", {}).items():
            try:
                text = await self.get_html(url)
                proxies.extend(self._parse_text(text, protocol=protocol))
            except Exception as e:
                logger.warning("VMHeavenFetcher protocol={} error: {}", protocol, e)
        return proxies

class KangProxyFetcher(BaseFetcher):
    source = "kangproxy"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "kangproxy")
        if not cfg.get("enabled", True):
            return []
        proxies: list[Proxy] = []
        for protocol, url in cfg.get("urls", {}).items():
            try:
                text = await self.get_html(url)
                proxies.extend(self._parse_text(text, protocol=protocol))
            except Exception as e:
                logger.warning("KangProxyFetcher protocol={} error: {}", protocol, e)
        return proxies

class IplocateFetcher(BaseFetcher):
    source = "iplocate"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "iplocate")
        if not cfg.get("enabled", True):
            return []
        proxies: list[Proxy] = []
        for protocol, url in cfg.get("urls", {}).items():
            try:
                text = await self.get_html(url)
                proxies.extend(self._parse_text(text, protocol=protocol))
            except Exception as e:
                logger.warning("IplocateFetcher protocol={} error: {}", protocol, e)
        return proxies

class ErcinDedeogluFetcher(BaseFetcher):
    source = "ercindedeoglu"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "ercindedeoglu")
        if not cfg.get("enabled", True):
            return []
        proxies: list[Proxy] = []
        for protocol, url in cfg.get("urls", {}).items():
            try:
                text = await self.get_html(url)
                proxies.extend(self._parse_text(text, protocol=protocol))
            except Exception as e:
                logger.warning("ErcinDedeogluFetcher protocol={} error: {}", protocol, e)
        return proxies

class ZevtyardtFetcher(BaseFetcher):
    source = "zevtyardt"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "zevtyardt")
        if not cfg.get("enabled", True):
            return []
        proxies: list[Proxy] = []
        for protocol, url in cfg.get("urls", {}).items():
            try:
                text = await self.get_html(url)
                proxies.extend(self._parse_text(text, protocol=protocol))
            except Exception as e:
                logger.warning("ZevtyardtFetcher protocol={} error: {}", protocol, e)
        return proxies

class HideipFetcher(BaseFetcher):
    source = "hideip"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "hideip")
        if not cfg.get("enabled", True):
            return []
        proxies: list[Proxy] = []
        for protocol, url in cfg.get("urls", {}).items():
            try:
                text = await self.get_html(url)
                proxies.extend(self._parse_text(text, protocol=protocol))
            except Exception as e:
                logger.warning("HideipFetcher protocol={} error: {}", protocol, e)
        return proxies

class Mmpx12Fetcher(BaseFetcher):
    source = "mmpx12"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "mmpx12")
        if not cfg.get("enabled", True):
            return []
        proxies: list[Proxy] = []
        for protocol, url in cfg.get("urls", {}).items():
            try:
                text = await self.get_html(url)
                proxies.extend(self._parse_text(text, protocol=protocol))
            except Exception as e:
                logger.warning("Mmpx12Fetcher protocol={} error: {}", protocol, e)
        return proxies


# === NEW FETCHERS (added 2026-07-17) ===

class RoundproxiesFetcher(BaseFetcher):
    """JSON API — extracts ip, port, protocols[] — supports SOCKS5."""
    source = "roundproxies"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "roundproxies")
        if not cfg.get("enabled", True):
            return []
        proxies: list[Proxy] = []
        url_tpl = cfg.get("url_template", "")
        for page in range(1, cfg.get("pages", 5) + 1):
            url = url_tpl.format(page=page)
            try:
                data = await self.get_json(url)
                for item in data.get("data", []):
                    host = item.get("ip", "")
                    port = item.get("port", 0)
                    if not host or not port:
                        continue
                    for proto in item.get("protocols", ["http"]):
                        try:
                            proxies.append(Proxy(
                                host=host, port=int(port),
                                protocol=proto.lower(), source=self.source,
                            ))
                        except Exception:
                            pass
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.warning("RoundproxiesFetcher page={} error: {}", page, e)
        return proxies


class FreevpnnodeFetcher(BaseFetcher):
    """HTML table with protocol column — col[0]=IP, col[1]=port, col[5]=protocol."""
    source = "freevpnnode"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "freevpnnode")
        if not cfg.get("enabled", True):
            return []
        url = cfg.get("url", "")
        try:
            html = await self.get_html(url)
            soup = BeautifulSoup(html, "lxml")
            proxies = []
            for tr in soup.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) < 6:
                    continue
                ip = tds[0].get_text(strip=True)
                port_text = tds[1].get_text(strip=True)
                protocol = tds[5].get_text(strip=True).lower()
                if not re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", ip):
                    continue
                if protocol not in ("http", "https", "socks4", "socks5"):
                    protocol = "http"
                try:
                    proxies.append(Proxy(
                        host=ip, port=int(port_text),
                        protocol=protocol, source=self.source,
                    ))
                except Exception:
                    pass
            return proxies
        except Exception as e:
            logger.warning("FreevpnnodeFetcher error: {}", e)
            return []


class SslProxiesFetcher(BaseFetcher):
    """Classic SSL proxy list — HTML table col[0]=IP, col[1]=port."""
    source = "sslproxies"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "sslproxies")
        if not cfg.get("enabled", True):
            return []
        try:
            html = await self.get_html(cfg["url"])
            return self._parse_table(html)
        except Exception as e:
            logger.warning("SslProxiesFetcher error: {}", e)
            return []


class UsProxyFetcher(BaseFetcher):
    """US proxy list — HTML table col[0]=IP, col[1]=port."""
    source = "usproxy"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "usproxy")
        if not cfg.get("enabled", True):
            return []
        try:
            html = await self.get_html(cfg["url"])
            return self._parse_table(html)
        except Exception as e:
            logger.warning("UsProxyFetcher error: {}", e)
            return []


class FreeProxyListFetcher(BaseFetcher):
    """THE classic free-proxy-list.net — HTML table col[0]=IP, col[1]=port."""
    source = "freeproxylist"

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "freeproxylist")
        if not cfg.get("enabled", True):
            return []
        try:
            html = await self.get_html(cfg["url"])
            return self._parse_table(html)
        except Exception as e:
            logger.warning("FreeProxyListFetcher error: {}", e)
            return []
