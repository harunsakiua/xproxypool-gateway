import asyncio
import re
import time
from datetime import datetime, timezone

import aiohttp

from proxy_pool.core.storage import storage
from proxy_pool.schemas.proxy import Proxy
from proxy_pool.utils.config import settings
from proxy_pool.utils.ip_region import lookup
from proxy_pool.utils.logger import logger

# --------------------------------------------------------------------------- #
# Verify helpers
# --------------------------------------------------------------------------- #

async def _verify_eastmoney(resp: aiohttp.ClientResponse) -> bool:
    """
    Accept HTTP 200 with East Money page content, OR a 3xx redirect whose
    Location contains 'eastmoney'.
    Reject empty responses, ad/hijack pages, and non-HTML proxy error pages.
    """
    if resp.status == 200:
        try:
            text = await resp.text(encoding="utf-8", errors="ignore")
            if len(text.strip()) < 100:
                return False
            text_lower = text.lower()
            hijack_signs = [
                "proxy", "captcha", "blocked", "forbidden",
                "ad_", "advert", "banner", "click here",
                "buy now", "subscribe", "casino", "betting",
            ]
            if any(sign in text_lower for sign in hijack_signs):
                if "东方财富" not in text and "eastmoney" not in text_lower:
                    return False
            return "东方财富" in text or "eastmoney" in text_lower
        except Exception:
            return False
    if resp.status in (301, 302, 307, 308):
        location = resp.headers.get("Location", "")
        return "eastmoney" in location.lower()
    return False

async def _verify_ipify(resp: aiohttp.ClientResponse) -> bool:
    """api.ipify.org returns a plain-text IPv4 address on HTTP 200 — no redirect."""
    if resp.status != 200:
        return False
    try:
        text = (await resp.text()).strip()
        return bool(re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", text))
    except Exception:
        return False

CN_TARGET   = ("http://www.eastmoney.com", _verify_eastmoney)
INTL_TARGET = ("http://api.ipify.org", _verify_ipify)

MAX_PING_MS = 8000

# --------------------------------------------------------------------------- #
# Per-proxy connector factory
# --------------------------------------------------------------------------- #

def _make_connector(proxy: Proxy) -> aiohttp.BaseConnector:
    """
    SOCKS4/SOCKS5 proxies require aiohttp-socks ProxyConnector — the
    connector itself handles the SOCKS handshake at the TCP level.
    HTTP/HTTPS proxies use a plain TCPConnector; the proxy URL is passed
    as a keyword argument to session.get().

    force_close=True: send Connection: close and release the TCP socket
    immediately after each response, preventing CLOSE_WAIT buildup.
    """
    if proxy.protocol in ("socks4", "socks5"):
        from aiohttp_socks import ProxyConnector
        return ProxyConnector.from_url(proxy.url, ssl=False, force_close=True)
    return aiohttp.TCPConnector(ssl=False, force_close=True)

def _proxy_kwarg(proxy: Proxy) -> dict:
    """
    Return {'proxy': proxy.url} for HTTP proxies.
    Return {} for SOCKS proxies (the connector handles routing).
    """
    if proxy.protocol in ("socks4", "socks5"):
        return {}
    return {"proxy": proxy.url}

# --------------------------------------------------------------------------- #
# Low-level checks — each creates (and closes) its own connector/session
# --------------------------------------------------------------------------- #

async def _check_cn(proxy: Proxy) -> tuple[bool, int]:
    """
    Test proxy against the CN target (Baidu).
    allow_redirects=False ensures every byte of the HTTP exchange goes
    through the tested proxy — no silent fallback to a direct connection
    on the redirect leg.
    connector_owner=False + explicit finally guarantees the connector is
    closed even if ClientSession.__init__ or __aenter__ itself raises.
    """
    url, verify_fn = CN_TARGET
    connector = _make_connector(proxy)
    start = time.monotonic()
    try:
        async with aiohttp.ClientSession(
            connector=connector,
            connector_owner=False,
            trust_env=False,
        ) as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=settings.validator_timeout),
                allow_redirects=False,
                ssl=False,
                **_proxy_kwarg(proxy),
            ) as resp:
                ping_ms = int((time.monotonic() - start) * 1000)
                if ping_ms > MAX_PING_MS:
                    return False, 0
                ok = await verify_fn(resp)
                return ok, ping_ms if ok else 0
    except Exception:
        return False, 0
    finally:
        await connector.close()

async def _check_intl(proxy: Proxy) -> tuple[bool, int]:
    """
    Test proxy against the INTL target (api.ipify.org — plain HTTP 200,
    no redirect).  allow_redirects=False to be consistent and safe.
    connector_owner=False + explicit finally guarantees the connector is
    closed even if ClientSession.__init__ or __aenter__ itself raises.
    """
    url, verify_fn = INTL_TARGET
    connector = _make_connector(proxy)
    start = time.monotonic()
    try:
        async with aiohttp.ClientSession(
            connector=connector,
            connector_owner=False,
            trust_env=False,
        ) as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=settings.validator_timeout),
                allow_redirects=False,
                ssl=False,
                **_proxy_kwarg(proxy),
            ) as resp:
                ping_ms = int((time.monotonic() - start) * 1000)
                if ping_ms > MAX_PING_MS:
                    return False, 0
                ok = await verify_fn(resp)
                return ok, ping_ms if ok else 0
    except Exception:
        return False, 0
    finally:
        await connector.close()

# --------------------------------------------------------------------------- #
# Worker-pool helper
# --------------------------------------------------------------------------- #

async def _run_workers(
    proxies: list[Proxy],
    task_fn,          # async (proxy) -> None
    concurrency: int,
    stop: asyncio.Event | None = None,
) -> None:
    """
    Process proxies with exactly `concurrency` worker coroutines.
    Only `concurrency` task objects ever exist simultaneously — the queue
    drains one item at a time per worker, so 30 000 proxies never spawn
    30 000 pending asyncio Tasks.
    When `stop` is set, workers drain remaining queue items without calling
    task_fn so the event loop doesn't stall on a huge queue.
    """
    queue: asyncio.Queue[Proxy] = asyncio.Queue()
    for p in proxies:
        queue.put_nowait(p)

    async def _worker() -> None:
        while True:
            try:
                proxy = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                if stop is None or not stop.is_set():
                    await task_fn(proxy)
            except Exception:
                pass
            finally:
                queue.task_done()

    await asyncio.gather(*[_worker() for _ in range(min(concurrency, len(proxies)))])

# --------------------------------------------------------------------------- #
# High-level validate jobs
# --------------------------------------------------------------------------- #

async def validate_new(proxies: list[Proxy]) -> None:
    """
    Validate freshly-fetched proxies.
    Classification is based on IP geolocation (ip2region):
      - Chinese IPs → validate against CN target → CN pool
      - Non-Chinese IPs → validate against INTL target → INTL pool
    Stops as soon as both pools reach proxy_cap.
    """
    if not proxies:
        return

    cn_cap = settings.cn_proxy_cap
    intl_cap = settings.intl_proxy_cap
    stop = asyncio.Event()

    async def _task(proxy: Proxy) -> None:
        # Classify by IP geolocation (fast, in-memory lookup)
        region = lookup(proxy.host)
        is_cn = region.startswith("中国")

        # Quick check: skip if target pool is full; stop if both full
        cn_count, intl_count = await asyncio.gather(
            storage.cn.count_success(),
            storage.intl.count_success(),
        )
        cn_full = cn_cap > 0 and cn_count >= cn_cap
        intl_full = intl_cap > 0 and intl_count >= intl_cap
        if cn_full and intl_full:
            stop.set()
            return
        if is_cn and cn_full:
            return
        if not is_cn and intl_full:
            return

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        if is_cn:
            ok, ping = await _check_cn(proxy)
            if ok:
                p = proxy.model_copy(update={
                    "ping": ping, "last_check": now,
                    "score": settings.score_init, "region": region,
                })
                added = await storage.cn.add_if_under_cap(p, cn_cap)
                if added:
                    logger.debug("New cn proxy OK: {} ({}ms) [{}]", proxy.string, ping, region)
        else:
            ok, ping = await _check_intl(proxy)
            if ok:
                p = proxy.model_copy(update={
                    "ping": ping, "last_check": now,
                    "score": settings.score_init, "region": region,
                })
                added = await storage.intl.add_if_under_cap(p, intl_cap)
                if added:
                    logger.debug("New intl proxy OK: {} ({}ms) [{}]", proxy.string, ping, region)

    await _run_workers(proxies, _task, settings.validator_concurrency, stop=stop)
    logger.info("validate_new done: {} proxies checked", len(proxies))

async def validate_existing_cn(proxies: list[Proxy]) -> None:
    """
    Re-validate cn success proxies against Baidu.
    Pass  → score += SCORE_INCREMENT (capped at max), update ping.
    Fail  → score -= SCORE_DECREMENT; if score <= 0, move to recheck.
    """
    if not proxies:
        return

    async def _task(proxy: Proxy) -> None:
        ok, ping = await _check_cn(proxy)
        proxy.last_check = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if ok:
            proxy.score = min(proxy.score + settings.score_increment, settings.score_max)
            proxy.ping = ping
            if not proxy.region:
                proxy.region = lookup(proxy.host)
            await storage.cn.update(proxy)
            logger.debug("cn proxy OK: {} score={} ping={}ms", proxy.string, proxy.score, ping)
        else:
            proxy.score -= settings.score_decrement
            if proxy.score <= 0:
                await storage.cn.move_to_recheck(proxy)
            else:
                await storage.cn.update(proxy)
            logger.debug("cn proxy FAIL: {} score={}", proxy.string, proxy.score)

    await _run_workers(proxies, _task, settings.validator_concurrency)
    logger.info("validate_existing_cn done: {} proxies checked", len(proxies))

async def validate_existing_intl(proxies: list[Proxy]) -> None:
    """
    Re-validate intl success proxies against api.ipify.org.
    Pass  → score += SCORE_INCREMENT (capped at max), update ping.
    Fail  → score -= SCORE_DECREMENT; if score <= 0, move to recheck.
    """
    if not proxies:
        return

    async def _task(proxy: Proxy) -> None:
        ok, ping = await _check_intl(proxy)
        proxy.last_check = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if ok:
            proxy.score = min(proxy.score + settings.score_increment, settings.score_max)
            proxy.ping = ping
            if not proxy.region:
                proxy.region = lookup(proxy.host)
            await storage.intl.update(proxy)
            logger.debug("intl proxy OK: {} score={} ping={}ms", proxy.string, proxy.score, ping)
        else:
            proxy.score -= settings.score_decrement
            if proxy.score <= 0:
                await storage.intl.move_to_recheck(proxy)
            else:
                await storage.intl.update(proxy)
            logger.debug("intl proxy FAIL: {} score={}", proxy.string, proxy.score)

    await _run_workers(proxies, _task, settings.validator_concurrency)
    logger.info("validate_existing_intl done: {} proxies checked", len(proxies))

async def validate_recheck_cn(proxies: list[Proxy]) -> None:
    """
    Re-validate cn recheck proxies against Baidu.
    Pass  → reset score to SCORE_INIT, move back to success (if under cap).
    Fail  → delete permanently.
    """
    if not proxies:
        return
    cn_cap = settings.cn_proxy_cap

    async def _task(proxy: Proxy) -> None:
        ok, ping = await _check_cn(proxy)
        proxy.last_check = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if ok:
            proxy.score = settings.score_init
            proxy.ping = ping
            if not proxy.region:
                proxy.region = lookup(proxy.host)
            restored = await storage.cn.restore_if_under_cap(proxy, cn_cap)
            if restored:
                logger.debug("cn recheck proxy revived: {} ping={}ms", proxy.string, ping)
            else:
                await storage.cn.delete(proxy.string)
                logger.debug("cn recheck proxy passed but pool full, removed: {}", proxy.string)
        else:
            await storage.cn.delete(proxy.string)
            logger.debug("cn recheck proxy deleted: {}", proxy.string)

    await _run_workers(proxies, _task, settings.validator_concurrency)
    logger.info("validate_recheck_cn done: {} proxies checked", len(proxies))

async def validate_recheck_intl(proxies: list[Proxy]) -> None:
    """
    Re-validate intl recheck proxies against api.ipify.org.
    Pass  → reset score to SCORE_INIT, move back to success (if under cap).
    Fail  → delete permanently.
    """
    if not proxies:
        return
    intl_cap = settings.intl_proxy_cap

    async def _task(proxy: Proxy) -> None:
        ok, ping = await _check_intl(proxy)
        proxy.last_check = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if ok:
            proxy.score = settings.score_init
            proxy.ping = ping
            if not proxy.region:
                proxy.region = lookup(proxy.host)
            restored = await storage.intl.restore_if_under_cap(proxy, intl_cap)
            if restored:
                logger.debug("intl recheck proxy revived: {} ping={}ms", proxy.string, ping)
            else:
                await storage.intl.delete(proxy.string)
                logger.debug("intl recheck proxy passed but pool full, removed: {}", proxy.string)
        else:
            await storage.intl.delete(proxy.string)
            logger.debug("intl recheck proxy deleted: {}", proxy.string)

    await _run_workers(proxies, _task, settings.validator_concurrency)
    logger.info("validate_recheck_intl done: {} proxies checked", len(proxies))
