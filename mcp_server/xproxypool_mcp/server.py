"""MCP server exposing read-only inspection of Xproxypool's Redis state.

Configured via environment variables (with sensible defaults for the
docker-compose mapping at 127.0.0.1:6380):

    XPROXYPOOL_REDIS_HOST       default 127.0.0.1
    XPROXYPOOL_REDIS_PORT       default 6380
    XPROXYPOOL_REDIS_DB         default 0
    XPROXYPOOL_REDIS_PASSWORD   default empty

Run via `xproxypool-mcp` after `pip install -e .`, or directly:
    python -m xproxypool_mcp.server
"""
from __future__ import annotations

import json
import os
import random
from typing import Optional

import redis
from mcp.server.fastmcp import FastMCP

# --------------------------------------------------------------------------- #
# Redis connection — lazy, single shared client
# --------------------------------------------------------------------------- #

_REDIS_HOST = os.environ.get("XPROXYPOOL_REDIS_HOST", "127.0.0.1")
_REDIS_PORT = int(os.environ.get("XPROXYPOOL_REDIS_PORT", "6380"))
_REDIS_DB = int(os.environ.get("XPROXYPOOL_REDIS_DB", "0"))
_REDIS_PASSWORD = os.environ.get("XPROXYPOOL_REDIS_PASSWORD") or None

_client: Optional[redis.Redis] = None


def _r() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis(
            host=_REDIS_HOST,
            port=_REDIS_PORT,
            db=_REDIS_DB,
            password=_REDIS_PASSWORD,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
    return _client


def _key(pool: str, kind: str) -> str:
    if pool not in ("cn", "intl"):
        raise ValueError(f"pool must be 'cn' or 'intl', got {pool!r}")
    if kind not in ("success", "recheck"):
        raise ValueError(f"kind must be 'success' or 'recheck', got {kind!r}")
    return f"proxy:{pool}:{kind}"


def _parse(values: list) -> list[dict]:
    out: list[dict] = []
    for v in values:
        if not v:
            continue
        try:
            out.append(json.loads(v))
        except json.JSONDecodeError:
            pass
    return out


# --------------------------------------------------------------------------- #
# MCP server
# --------------------------------------------------------------------------- #

mcp = FastMCP("xproxypool")


@mcp.tool()
def pool_stats() -> dict:
    """Get health stats for both proxy pools.

    Returns counts and quality metrics for cn (Chinese-IP proxies) and
    intl (overseas-IP proxies). Useful as the first call to get an
    overview before drilling down.

    Returns:
        {
          "cn":   {"success": int, "recheck": int, "avg_score": float,
                   "avg_ping_ms": int, "sources": {source: count, ...}},
          "intl": { ...same shape... }
        }
    """
    out = {}
    for pool in ("cn", "intl"):
        proxies = _parse(_r().hvals(_key(pool, "success")))
        recheck_count = _r().hlen(_key(pool, "recheck"))
        n = len(proxies)
        sources: dict[str, int] = {}
        for p in proxies:
            s = p.get("source", "unknown")
            sources[s] = sources.get(s, 0) + 1
        out[pool] = {
            "success": n,
            "recheck": recheck_count,
            "avg_score": round(sum(p.get("score", 0) for p in proxies) / n, 1) if n else 0,
            "avg_ping_ms": int(sum(p.get("ping", 0) for p in proxies) / n) if n else 0,
            "sources": dict(sorted(sources.items(), key=lambda x: -x[1])),
        }
    return out


@mcp.tool()
def random_proxy(
    pool: str = "cn",
    protocol: Optional[str] = None,
    min_score: int = 50,
) -> Optional[dict]:
    """Pick a random proxy from a pool, optionally filtered.

    Args:
        pool: 'cn' (Chinese IPs) or 'intl' (overseas IPs)
        protocol: 'http' / 'https' / 'socks4' / 'socks5'; None = any
        min_score: minimum score (0-100); default 50

    Returns:
        Full proxy dict, or None if no candidate matches.
    """
    proxies = _parse(_r().hvals(_key(pool, "success")))
    candidates = [
        p for p in proxies
        if p.get("score", 0) >= min_score
        and (protocol is None or p.get("protocol") == protocol)
    ]
    return random.choice(candidates) if candidates else None


@mcp.tool()
def list_proxies(
    pool: str = "cn",
    limit: int = 20,
    min_score: int = 0,
    protocol: Optional[str] = None,
    region_contains: Optional[str] = None,
    sort_by: str = "score",
) -> list[dict]:
    """List proxies in a pool with optional filters and sorting.

    Args:
        pool: 'cn' or 'intl'
        limit: max rows to return (default 20)
        min_score: only return proxies with score >= this
        protocol: filter by protocol; None = any
        region_contains: substring match on region field
                         (e.g., '上海', 'United States', '电信')
        sort_by: 'score' (highest first), 'ping' (lowest first),
                 'created_at' (newest first), 'last_check' (most recent first)
    """
    proxies = _parse(_r().hvals(_key(pool, "success")))
    filtered = [
        p for p in proxies
        if p.get("score", 0) >= min_score
        and (protocol is None or p.get("protocol") == protocol)
        and (region_contains is None or region_contains in p.get("region", ""))
    ]

    sorters = {
        "score":      (lambda p: -p.get("score", 0)),
        "ping":       (lambda p:  p.get("ping", 10**9)),
        "created_at": (lambda p:  p.get("created_at", "")),
        "last_check": (lambda p:  p.get("last_check", "")),
    }
    sorter = sorters.get(sort_by, sorters["score"])
    reverse = sort_by in ("created_at", "last_check")
    filtered.sort(key=sorter, reverse=reverse)

    return filtered[:max(1, limit)]


@mcp.tool()
def proxy_detail(ip_port: str, pool: str = "cn") -> Optional[dict]:
    """Look up a specific proxy's full record, in either success or recheck.

    Args:
        ip_port: 'host:port' string, e.g. '1.2.3.4:8080'
        pool: 'cn' or 'intl'

    Returns:
        Full proxy dict with an extra 'state' key ('success' / 'recheck'),
        or None if the proxy is not in this pool.
    """
    for kind in ("success", "recheck"):
        v = _r().hget(_key(pool, kind), ip_port)
        if v:
            d = json.loads(v)
            d["state"] = kind
            return d
    return None


@mcp.tool()
def count_by_source(pool: str = "cn") -> dict:
    """Group success proxies by fetcher source, with quality metrics per source.

    Use this to identify which sources are pulling their weight and which
    should be disabled in sources.yml. Sources at very low avg_score
    relative to their count are the prime candidates for deactivation.

    Returns:
        {source_name: {count: int, avg_score: float, avg_ping_ms: int}}
        sorted by count descending.
    """
    proxies = _parse(_r().hvals(_key(pool, "success")))
    grouped: dict = {}
    for p in proxies:
        s = p.get("source", "unknown")
        if s not in grouped:
            grouped[s] = {"count": 0, "_score": 0, "_ping": 0}
        grouped[s]["count"] += 1
        grouped[s]["_score"] += p.get("score", 0)
        grouped[s]["_ping"] += p.get("ping", 0)
    out: dict = {}
    for s, v in sorted(grouped.items(), key=lambda x: -x[1]["count"]):
        n = v["count"]
        out[s] = {
            "count": n,
            "avg_score": round(v["_score"] / n, 1),
            "avg_ping_ms": int(v["_ping"] / n),
        }
    return out


@mcp.tool()
def count_by_region(pool: str = "cn", top_n: int = 10) -> dict:
    """Top-N most-populated regions in the success pool.

    Each proxy's region is a pipe-delimited string from ip2region, e.g.
    '中国|0|上海|上海市|电信' or 'United States|California|...'.
    This groups by the exact region string.

    Args:
        top_n: max regions to return (1-100)
    """
    top_n = max(1, min(top_n, 100))
    counts: dict[str, int] = {}
    for p in _parse(_r().hvals(_key(pool, "success"))):
        region = p.get("region", "unknown")
        counts[region] = counts.get(region, 0) + 1
    top = sorted(counts.items(), key=lambda x: -x[1])[:top_n]
    return dict(top)


@mcp.tool()
def list_recheck(pool: str = "cn", limit: int = 20) -> list[dict]:
    """List proxies in the recheck pool — these have score <= 0 and are
    one validation cycle away from being permanently deleted (or revived).

    Useful for diagnosing which sources contribute the most failing proxies.
    Combine with `count_by_source` on the recheck snapshot for trend analysis.

    Args:
        limit: max rows (default 20)
    """
    proxies = _parse(_r().hvals(_key(pool, "recheck")))
    proxies.sort(key=lambda p: p.get("last_check", ""), reverse=True)
    return proxies[:max(1, limit)]


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
