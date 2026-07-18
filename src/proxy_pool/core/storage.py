import random
from typing import Optional

import redis.asyncio as aioredis

from proxy_pool.schemas.proxy import Proxy
from proxy_pool.utils.config import settings
from proxy_pool.utils.logger import logger

# --------------------------------------------------------------------------- #
# Lua scripts for atomic cap-safe operations
# --------------------------------------------------------------------------- #

# Atomically: check cap, check exists in both hashes, then add to success.
# KEYS[1]=success_key  KEYS[2]=recheck_key
# ARGV[1]=cap  ARGV[2]=proxy_string  ARGV[3]=proxy_json
# Returns 1 if added, 0 if cap reached or already exists.
_ADD_IF_UNDER_CAP_LUA = """
local cap = tonumber(ARGV[1])
if cap > 0 then
    local count = redis.call('HLEN', KEYS[1])
    if count >= cap then
        return 0
    end
end
if redis.call('HEXISTS', KEYS[1], ARGV[2]) == 1 then
    return 0
end
if redis.call('HEXISTS', KEYS[2], ARGV[2]) == 1 then
    return 0
end
redis.call('HSET', KEYS[1], ARGV[2], ARGV[3])
return 1
"""

# Atomically: check cap, move proxy from recheck to success.
# KEYS[1]=success_key  KEYS[2]=recheck_key
# ARGV[1]=cap  ARGV[2]=proxy_string  ARGV[3]=proxy_json
# Returns 1 if restored, 0 if cap reached.
_RESTORE_IF_UNDER_CAP_LUA = """
local cap = tonumber(ARGV[1])
if cap > 0 then
    local count = redis.call('HLEN', KEYS[1])
    if count >= cap then
        return 0
    end
end
redis.call('HDEL', KEYS[2], ARGV[2])
redis.call('HSET', KEYS[1], ARGV[2], ARGV[3])
return 1
"""

class PoolStorage:
    """Manages one named pool (cn or intl) using two Redis Hashes."""

    def __init__(self, client: aioredis.Redis, name: str) -> None:
        self._client = client
        self.name = name
        self.success_key = f"proxy:{name}:success"
        self.recheck_key = f"proxy:{name}:recheck"

    # ------------------------------------------------------------------ #
    # Write operations
    # ------------------------------------------------------------------ #

    async def exists(self, proxy_string: str) -> bool:
        """True if proxy exists in either success or recheck hash."""
        return bool(
            await self._client.hexists(self.success_key, proxy_string)
            or await self._client.hexists(self.recheck_key, proxy_string)
        )

    async def add(self, proxy: Proxy) -> None:
        """Add a new proxy directly into success hash."""
        await self._client.hset(self.success_key, proxy.string, proxy.model_dump_json())

    async def add_if_under_cap(self, proxy: Proxy, cap: int) -> bool:
        """Atomically add proxy to success only if count < cap and not already known.
        Returns True if added."""
        result = await self._client.eval(
            _ADD_IF_UNDER_CAP_LUA, 2,
            self.success_key, self.recheck_key,
            cap, proxy.string, proxy.model_dump_json(),
        )
        return bool(result)

    async def update(self, proxy: Proxy) -> None:
        """Overwrite proxy data in success hash (after validation updates score/ping)."""
        await self._client.hset(self.success_key, proxy.string, proxy.model_dump_json())

    async def move_to_recheck(self, proxy: Proxy) -> None:
        await self._client.hdel(self.success_key, proxy.string)
        await self._client.hset(self.recheck_key, proxy.string, proxy.model_dump_json())
        logger.debug("[{}] Moved to recheck: {}", self.name, proxy.string)

    async def add_to_success(self, proxy: Proxy) -> None:
        await self._client.hdel(self.recheck_key, proxy.string)
        await self._client.hset(self.success_key, proxy.string, proxy.model_dump_json())

    async def restore_if_under_cap(self, proxy: Proxy, cap: int) -> bool:
        """Atomically move proxy from recheck to success only if count < cap.
        Returns True if restored."""
        result = await self._client.eval(
            _RESTORE_IF_UNDER_CAP_LUA, 2,
            self.success_key, self.recheck_key,
            cap, proxy.string, proxy.model_dump_json(),
        )
        return bool(result)

    async def delete(self, proxy_string: str) -> None:
        await self._client.hdel(self.success_key, proxy_string)
        await self._client.hdel(self.recheck_key, proxy_string)
        logger.debug("[{}] Deleted proxy: {}", self.name, proxy_string)

    # ------------------------------------------------------------------ #
    # Read operations
    # ------------------------------------------------------------------ #

    async def get(self, proxy_string: str) -> Optional[Proxy]:
        data = await self._client.hget(self.success_key, proxy_string)
        if data:
            return Proxy.model_validate_json(data)
        data = await self._client.hget(self.recheck_key, proxy_string)
        if data:
            return Proxy.model_validate_json(data)
        return None

    async def count_success(self) -> int:
        return await self._client.hlen(self.success_key)

    async def get_success_list(self) -> list[Proxy]:
        values = await self._client.hvals(self.success_key)
        return self._parse_list(values)

    async def get_recheck_list(self) -> list[Proxy]:
        values = await self._client.hvals(self.recheck_key)
        return self._parse_list(values)

    async def get_all_keys(self) -> set[str]:
        """Return all proxy key strings from both success and recheck hashes."""
        import asyncio as _asyncio
        success_keys, recheck_keys = await _asyncio.gather(
            self._client.hkeys(self.success_key),
            self._client.hkeys(self.recheck_key),
        )
        return set(success_keys) | set(recheck_keys)

    def _parse_list(self, values: list) -> list[Proxy]:
        result = []
        for v in values:
            if v:
                try:
                    result.append(Proxy.model_validate_json(v))
                except Exception:
                    pass
        return result

    async def get_random(
        self, min_score: int = 50, protocol: Optional[str] = None
    ) -> Optional[Proxy]:
        proxies = await self.get_success_list()
        candidates = [
            p for p in proxies
            if p.score >= min_score and (protocol is None or p.protocol == protocol)
        ]
        if not candidates:
            return None
        return random.choice(candidates)

    # ------------------------------------------------------------------ #
    # Stats
    # ------------------------------------------------------------------ #

    async def stats(self) -> dict:
        success_proxies = await self.get_success_list()
        recheck_count = await self._client.hlen(self.recheck_key)
        avg_score = (
            round(sum(p.score for p in success_proxies) / len(success_proxies), 1)
            if success_proxies
            else 0
        )
        source_counts: dict[str, int] = {}
        for p in success_proxies:
            key = p.source or "unknown"
            source_counts[key] = source_counts.get(key, 0) + 1
        return {
            "success": len(success_proxies),
            "recheck": recheck_count,
            "avg_score": avg_score,
            "sources": source_counts,
        }

class RedisStorage:
    def __init__(self) -> None:
        self._client: Optional[aioredis.Redis] = None
        self.cn: Optional[PoolStorage] = None
        self.intl: Optional[PoolStorage] = None

    async def connect(self) -> None:
        self._client = aioredis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password or None,
            db=settings.redis_db,
            decode_responses=True,
            max_connections=settings.validator_concurrency + 10,
        )
        await self._client.ping()
        self.cn = PoolStorage(self._client, "cn")
        self.intl = PoolStorage(self._client, "intl")
        logger.info("Redis connected at {}:{}", settings.redis_host, settings.redis_port)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def stats(self) -> dict:
        return {
            "cn": await self.cn.stats(),
            "intl": await self.intl.stats(),
        }

storage = RedisStorage()
