from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from proxy_pool.core.storage import storage
from proxy_pool.utils.logger import logger

router = APIRouter()

PoolName = Literal["cn", "intl"]

def _get_pool(pool: str):
    if pool == "cn":
        return storage.cn
    if pool == "intl":
        return storage.intl
    raise HTTPException(status_code=400, detail="pool must be 'cn' or 'intl'")

@router.get("/get")
async def get_proxy(
    pool: PoolName = Query("cn", description="Proxy pool to query: cn or intl"),
    protocol: Optional[str] = Query(None, description="Filter by protocol: http/https/socks5"),
    min_score: int = Query(50, ge=0, le=100, description="Minimum proxy score"),
    format: Optional[str] = Query(None, description="Use 'text' for plain ip:port response"),
):
    """Return a single random proxy from the given pool satisfying the filters."""
    proxy = await _get_pool(pool).get_random(min_score=min_score, protocol=protocol)
    if proxy is None:
        raise HTTPException(status_code=404, detail="No proxy available matching the criteria")

    if format == "text":
        return PlainTextResponse(f"{proxy.protocol}://{proxy.string}")

    return proxy.model_dump()

@router.get("/all")
async def get_all(
    pool: PoolName = Query("cn", description="Proxy pool to query: cn or intl"),
    protocol: Optional[str] = Query(None, description="Filter by protocol"),
):
    """Return all proxies currently in the given pool's success set."""
    proxies = await _get_pool(pool).get_success_list()
    if protocol:
        proxies = [p for p in proxies if p.protocol == protocol]
    return [p.model_dump() for p in proxies]

@router.get("/stats")
async def get_stats():
    """Return pool statistics for both cn and intl pools."""
    return await storage.stats()

@router.delete("/delete")
async def delete_proxy(
    proxy: str = Query(..., description="ip:port to delete"),
    pool: PoolName = Query("cn", description="Proxy pool to delete from: cn or intl"),
):
    """Manually remove a proxy from the specified pool."""
    pool_storage = _get_pool(pool)
    existing = await pool_storage.get(proxy)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Proxy {proxy!r} not found in pool '{pool}'")
    await pool_storage.delete(proxy)
    logger.info("Manually deleted proxy {} from pool '{}'", proxy, pool)
    return {"deleted": proxy, "pool": pool}
