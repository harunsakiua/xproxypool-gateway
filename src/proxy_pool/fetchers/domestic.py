"""
Domestic (Chinese) proxy fetchers — 6 sources.
URLs are configured in sources.yml at the project root.
"""

import asyncio

from bs4 import BeautifulSoup

from proxy_pool.fetchers.base import BaseFetcher
from proxy_pool.schemas.proxy import Proxy
from proxy_pool.utils.logger import logger
from proxy_pool.utils.sources import get

class KuaidailiFetcher(BaseFetcher):
    source = "kuaidaili"

    async def fetch(self) -> list[Proxy]:
        cfg = get("domestic", "kuaidaili")
        if not cfg.get("enabled", True):
            return []
        proxies: list[Proxy] = []
        for url_tpl in cfg.get("url_templates", []):
            for page in range(1, cfg.get("pages", 3) + 1):
                url = url_tpl.format(page=page)
                try:
                    html = await self.get_html(url)
                    proxies.extend(self._parse_table(html))
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.warning("KuaidailiFetcher url={} error: {}", url, e)
        return proxies

class Ip3366Fetcher(BaseFetcher):
    source = "ip3366"

    async def fetch(self) -> list[Proxy]:
        cfg = get("domestic", "ip3366")
        if not cfg.get("enabled", True):
            return []
        proxies: list[Proxy] = []
        for url_tpl in cfg.get("url_templates", []):
            for page in range(1, cfg.get("pages", 3) + 1):
                url = url_tpl.format(page=page)
                try:
                    html = await self.get_html(url)
                    proxies.extend(self._parse_table(html))
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.warning("Ip3366Fetcher url={} error: {}", url, e)
        return proxies

class KxdailiFetcher(BaseFetcher):
    source = "kxdaili"

    async def fetch(self) -> list[Proxy]:
        cfg = get("domestic", "kxdaili")
        if not cfg.get("enabled", True):
            return []
        proxies: list[Proxy] = []
        url_tpl = cfg.get("url_template", "")
        for page in range(1, cfg.get("pages", 3) + 1):
            url = url_tpl.format(page=page)
            try:
                html = await self.get_html(url)
                proxies.extend(self._parse_table(html))
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning("KxdailiFetcher url={} error: {}", url, e)
        return proxies

class Ip89Fetcher(BaseFetcher):
    source = "89ip"

    async def fetch(self) -> list[Proxy]:
        cfg = get("domestic", "ip89")
        if not cfg.get("enabled", True):
            return []
        url = cfg.get("url", "")
        try:
            text = await self.get_html(url)
            return self._parse_text(text)
        except Exception as e:
            logger.warning("Ip89Fetcher error: {}", e)
            return []

class DocipFetcher(BaseFetcher):
    source = "docip"

    async def fetch(self) -> list[Proxy]:
        cfg = get("domestic", "docip")
        if not cfg.get("enabled", True):
            return []
        url = cfg.get("url", "")
        try:
            data = await self.get_json(url)
            proxies = []
            items = data if isinstance(data, list) else data.get("data", [])
            for item in items:
                raw = item.get("ip", "")
                if ":" in raw:
                    host, port_str = raw.rsplit(":", 1)
                    try:
                        proxies.append(
                            Proxy(host=host, port=int(port_str), protocol="http", source=self.source)
                        )
                    except Exception:
                        pass
            return proxies
        except Exception as e:
            logger.warning("DocipFetcher error: {}", e)
            return []

class ZdayeFetcher(BaseFetcher):
    source = "zdaye"

    async def fetch(self) -> list[Proxy]:
        cfg = get("domestic", "zdaye")
        if not cfg.get("enabled", True):
            return []
        index_url = cfg.get("index_url", "")
        selector = cfg.get("selector", ".thread_item h3 a")
        try:
            index_html = await self.get_html(index_url)
            soup = BeautifulSoup(index_html, "lxml")
            link_tag = soup.select_one(selector)
            if not link_tag:
                return []
            href = link_tag.get("href", "")
            if not href.startswith("http"):
                href = "https://www.zdaye.com" + href
            html = await self.get_html(href)
            return self._parse_text(html)
        except Exception as e:
            logger.warning("ZdayeFetcher error: {}", e)
            return []
