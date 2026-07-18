import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from proxy_pool.core.storage import storage
from proxy_pool.core.validator import (
    validate_existing_cn,
    validate_existing_intl,
    validate_new,
    validate_recheck_cn,
    validate_recheck_intl,
)
from proxy_pool.fetchers import ALL_FETCHERS
from proxy_pool.utils.config import settings
from proxy_pool.utils.logger import logger

scheduler = AsyncIOScheduler()

async def fetch_job() -> None:
    """Run all fetchers concurrently, then validate the new proxies into both pools."""
    if settings.cn_proxy_cap > 0 or settings.intl_proxy_cap > 0:
        cn_count = await storage.cn.count_success()
        intl_count = await storage.intl.count_success()
        cn_full = settings.cn_proxy_cap > 0 and cn_count >= settings.cn_proxy_cap
        intl_full = settings.intl_proxy_cap > 0 and intl_count >= settings.intl_proxy_cap
        if cn_full and intl_full:
            logger.info(
                "fetch_job skipped: cn={}/{} intl={}/{} both full",
                cn_count, settings.cn_proxy_cap, intl_count, settings.intl_proxy_cap,
            )
            return

    logger.info("fetch_job started, running {} fetchers", len(ALL_FETCHERS))

    async def _run(fetcher_cls):
        fetcher = fetcher_cls()
        try:
            proxies = await fetcher.fetch()
            logger.info("{} fetched {} proxies", fetcher_cls.__name__, len(proxies))
            return proxies
        except Exception as exc:
            logger.warning("{} failed: {}", fetcher_cls.__name__, exc)
            return []

    results = await asyncio.gather(*[_run(f) for f in ALL_FETCHERS], return_exceptions=False)
    seen: set[str] = set()
    all_proxies = []
    for batch in results:
        for p in batch:
            if p.string not in seen:
                seen.add(p.string)
                all_proxies.append(p)
    logger.info("Total fetched (pre-validation, deduped): {}", len(all_proxies))

    # Pre-filter: skip proxies already known in either pool (each proxy belongs
    # to exactly one pool based on IP geolocation, so no need to re-validate).
    cn_known, intl_known = await asyncio.gather(
        storage.cn.get_all_keys(),
        storage.intl.get_all_keys(),
    )
    any_known = cn_known | intl_known
    if any_known:
        all_proxies = [p for p in all_proxies if p.string not in any_known]
        logger.info("After pre-filter (skip known): {} proxies to validate", len(all_proxies))

    await validate_new(all_proxies)

async def validate_success_job() -> None:
    """Validate proxies currently in both success sets, concurrently."""
    cn_proxies, intl_proxies = await asyncio.gather(
        storage.cn.get_success_list(),
        storage.intl.get_success_list(),
    )
    logger.info(
        "validate_success_job: cn={} intl={} proxies to check",
        len(cn_proxies), len(intl_proxies),
    )
    await asyncio.gather(
        validate_existing_cn(cn_proxies),
        validate_existing_intl(intl_proxies),
    )

async def validate_recheck_job() -> None:
    """Validate proxies in both recheck sets, concurrently."""
    cn_proxies, intl_proxies = await asyncio.gather(
        storage.cn.get_recheck_list(),
        storage.intl.get_recheck_list(),
    )
    logger.info(
        "validate_recheck_job: cn={} intl={} proxies to check",
        len(cn_proxies), len(intl_proxies),
    )
    await asyncio.gather(
        validate_recheck_cn(cn_proxies),
        validate_recheck_intl(intl_proxies),
    )

def setup_scheduler() -> None:
    scheduler.add_job(
        fetch_job,
        trigger=IntervalTrigger(minutes=settings.fetch_interval),
        id="fetch_job",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=None,
    )
    scheduler.add_job(
        validate_success_job,
        trigger=IntervalTrigger(minutes=settings.validate_interval),
        id="validate_success_job",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=None,
    )
    scheduler.add_job(
        validate_recheck_job,
        trigger=IntervalTrigger(minutes=settings.recheck_interval),
        id="validate_recheck_job",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=None,
    )
    logger.info(
        "Scheduler configured: fetch={}min, validate={}min, recheck={}min",
        settings.fetch_interval,
        settings.validate_interval,
        settings.recheck_interval,
    )
