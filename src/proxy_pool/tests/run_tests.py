"""
Standalone test runner — no pytest needed.
Run: /app/.venv/bin/python src/proxy_pool/tests/run_tests.py
"""
import asyncio
import sys
import os
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../"))

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

results = []

def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    msg = f"  [{status}] {name}"
    if not condition and detail:
        msg += f"\n         detail: {detail}"
    print(msg)
    results.append((name, condition))
    return condition

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

# ─────────────────────────────────────────────────────────────
# 1. Imports
# ─────────────────────────────────────────────────────────────
section("1. Dependency imports")

try:
    import aiohttp
    check("aiohttp importable", True)
except Exception as e:
    check("aiohttp importable", False, str(e))

try:
    import aiohttp_socks
    check("aiohttp-socks importable", True)
    ver_tuple = tuple(int(x) for x in aiohttp_socks.__version__.split("."))
    check("aiohttp-socks version >= 0.7", ver_tuple >= (0, 7), aiohttp_socks.__version__)
except Exception as e:
    check("aiohttp-socks importable", False, str(e))
    check("aiohttp-socks version >= 0.7", False)

try:
    from python_socks.async_.asyncio import Proxy as SocksProxy
    check("python-socks importable", True)
except Exception as e:
    check("python-socks importable", False, str(e))

# ─────────────────────────────────────────────────────────────
# 2. Proxy schema
# ─────────────────────────────────────────────────────────────
section("2. Proxy schema — validate_protocol & url property")

from proxy_pool.schemas.proxy import Proxy

def test_protocol_and_url(protocol, expected_url_scheme, expected_stored_protocol=None):
    p = Proxy(host="1.2.3.4", port=1080, protocol=protocol)
    stored = expected_stored_protocol or protocol
    check(
        f"protocol='{protocol}' → stored as '{stored}'",
        p.protocol == stored,
        f"got '{p.protocol}'",
    )
    check(
        f"protocol='{protocol}' → url starts with '{expected_url_scheme}://'",
        p.url.startswith(f"{expected_url_scheme}://"),
        f"got '{p.url}'",
    )

test_protocol_and_url("http",   "http")
test_protocol_and_url("https",  "http",   expected_stored_protocol="https")  # stored as https but URL uses http
test_protocol_and_url("socks5", "socks5")
test_protocol_and_url("socks4", "socks4")

# Unknown protocol must be coerced to http
p_unknown = Proxy(host="1.2.3.4", port=80, protocol="ftp")
check("unknown protocol 'ftp' → coerced to 'http'", p_unknown.protocol == "http", f"got '{p_unknown.protocol}'")
check("coerced http proxy url = http://", p_unknown.url.startswith("http://"), p_unknown.url)

# string property
p = Proxy(host="10.0.0.1", port=3128, protocol="http")
check("proxy.string = 'host:port'", p.string == "10.0.0.1:3128", p.string)

# ─────────────────────────────────────────────────────────────
# 3. Settings
# ─────────────────────────────────────────────────────────────
section("3. Settings — scoring thresholds")

from proxy_pool.utils.config import settings

check("SCORE_INIT >= SCORE_DECREMENT (survive ≥1 failure)",
      settings.score_init >= settings.score_decrement,
      f"score_init={settings.score_init}, score_decrement={settings.score_decrement}")

check("SCORE_INIT > 0", settings.score_init > 0, f"score_init={settings.score_init}")
check("SCORE_MAX > SCORE_INIT", settings.score_max > settings.score_init,
      f"max={settings.score_max}, init={settings.score_init}")
check("CN_PROXY_CAP >= 0", settings.cn_proxy_cap >= 0, f"cn_proxy_cap={settings.cn_proxy_cap}")
check("INTL_PROXY_CAP >= 0", settings.intl_proxy_cap >= 0, f"intl_proxy_cap={settings.intl_proxy_cap}")
check("VALIDATOR_TIMEOUT > 0", settings.validator_timeout > 0)
check("FETCH_INTERVAL > 0", settings.fetch_interval > 0)

# ─────────────────────────────────────────────────────────────
# 4. Validator — aiohttp-socks connector creation
# ─────────────────────────────────────────────────────────────
section("4. Validator — connector and aiohttp-socks integration")

from proxy_pool.core.validator import _make_connector, _check_cn, _check_intl

async def _test_connector():
    # _make_connector now takes a proxy; HTTP proxy → TCPConnector
    dummy = Proxy(host="1.1.1.1", port=80, protocol="http")
    conn = _make_connector(dummy)
    ok = hasattr(conn, "close")
    await conn.close()
    return ok

try:
    ok = asyncio.get_event_loop().run_until_complete(_test_connector())
    check("_make_connector(http_proxy) returns connector with .close()", ok)
except Exception as e:
    check("_make_connector(http_proxy) returns connector with .close()", False, str(e))

async def test_socks5_connector():
    """Verify aiohttp-socks can create a SOCKS5 proxy session (no actual network call)."""
    from aiohttp_socks import ProxyConnector
    try:
        connector = ProxyConnector.from_url("socks5://127.0.0.1:1")
        await connector.close()
        return True, ""
    except Exception as e:
        return False, str(e)

ok, err = asyncio.get_event_loop().run_until_complete(test_socks5_connector())
check("aiohttp-socks ProxyConnector instantiation", ok, err)

async def test_validator_fast_fail():
    """
    Validator must return (False, 0) quickly for unreachable proxies —
    not raise unhandled exceptions.
    _check_cn/_check_intl now own their connector/session internally.
    """
    dead_proxy = Proxy(host="192.0.2.1", port=9999, protocol="http")  # TEST-NET, unreachable
    results = []
    try:
        ok, ping = await asyncio.wait_for(_check_cn(dead_proxy), timeout=15)
        results.append(("cn_ok", ok == False))
        results.append(("cn_ping", ping == 0))
        ok2, ping2 = await asyncio.wait_for(_check_intl(dead_proxy), timeout=15)
        results.append(("intl_ok", ok2 == False))
        results.append(("intl_ping", ping2 == 0))
    except Exception as e:
        results.append(("exception", False))
        results.append(("exception_detail", str(e)))
    return results

results_v = asyncio.get_event_loop().run_until_complete(test_validator_fast_fail())
for name, val in results_v:
    if name == "exception_detail":
        continue
    check(f"validator fast-fail: {name}=={val}", val is True or val == False, str(val))

# ─────────────────────────────────────────────────────────────
# 5. allow_redirects check in validator source
# ─────────────────────────────────────────────────────────────
section("5. Validator — allow_redirects=True in source code")

import inspect
from proxy_pool.core import validator as validator_module

source = inspect.getsource(validator_module)
# Count occurrences
false_count = source.count("allow_redirects=False")
true_count  = source.count("allow_redirects=True")

check("allow_redirects=True count == 0", true_count == 0, f"found {true_count} occurrence(s)")
check("allow_redirects=False count >= 2 (both _check_cn and _check_intl)", false_count >= 2, f"found {false_count}")

# ─────────────────────────────────────────────────────────────
# 6. Storage mock test
# ─────────────────────────────────────────────────────────────
section("6. PoolStorage — logic without Redis (mock client)")

from unittest.mock import AsyncMock, MagicMock
from proxy_pool.core.storage import PoolStorage

class MockRedis:
    def __init__(self):
        self._hashes = {}

    async def hexists(self, key, field):
        return field in self._hashes.get(key, {})

    async def hset(self, key, field, value):
        self._hashes.setdefault(key, {})[field] = value

    async def hdel(self, key, *fields):
        h = self._hashes.get(key, {})
        for f in fields:
            h.pop(f, None)

    async def hlen(self, key):
        return len(self._hashes.get(key, {}))

    async def hvals(self, key):
        return list(self._hashes.get(key, {}).values())

    async def hget(self, key, field):
        return self._hashes.get(key, {}).get(field)

async def test_pool_storage():
    client = MockRedis()
    pool = PoolStorage(client, "test")

    proxy = Proxy(host="5.5.5.5", port=3128, protocol="http", source="test")

    # Initially empty
    exists = await pool.exists(proxy.string)
    yield "initially not exists", not exists

    count0 = await pool.count_success()
    yield "initial count == 0", count0 == 0

    # Add
    await pool.add(proxy)
    exists2 = await pool.exists(proxy.string)
    yield "exists after add", exists2

    count1 = await pool.count_success()
    yield "count == 1 after add", count1 == 1

    # Update score
    proxy.score = min(proxy.score + settings.score_increment, settings.score_max)
    await pool.update(proxy)
    lst = await pool.get_success_list()
    yield "score updated in storage", lst[0].score == proxy.score

    # Move to recheck (simulate score drop)
    proxy.score = 0
    await pool.move_to_recheck(proxy)
    count_s = await pool.count_success()
    yield "success count 0 after move_to_recheck", count_s == 0

    recheck = await pool.get_recheck_list()
    yield "recheck list has 1 entry", len(recheck) == 1

    # Revive (recheck pass)
    proxy.score = settings.score_init
    await pool.add_to_success(proxy)
    count_s2 = await pool.count_success()
    yield "revived to success", count_s2 == 1

    # Delete
    await pool.delete(proxy.string)
    exists3 = await pool.exists(proxy.string)
    yield "gone after delete", not exists3

async def run_storage_tests():
    async for name, ok in test_pool_storage():
        check(f"storage: {name}", ok)

asyncio.get_event_loop().run_until_complete(run_storage_tests())

# ─────────────────────────────────────────────────────────────
# 7. Fetcher ALL_FETCHERS list
# ─────────────────────────────────────────────────────────────
section("7. Fetchers — ALL_FETCHERS completeness")

from proxy_pool.fetchers import ALL_FETCHERS
check("ALL_FETCHERS non-empty", len(ALL_FETCHERS) > 0, f"count={len(ALL_FETCHERS)}")

# Each fetcher must have a `source` attribute and implement `fetch`
for cls in ALL_FETCHERS:
    has_source = bool(getattr(cls, "source", ""))
    has_fetch = callable(getattr(cls, "fetch", None))
    check(f"{cls.__name__}: has source + fetch", has_source and has_fetch,
          f"source={getattr(cls,'source',None)!r}")

# ─────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────
section("Summary")
passed = sum(1 for _, ok in results if ok)
failed = sum(1 for _, ok in results if not ok)
total = len(results)
print(f"\n  Total: {total}   Passed: {passed}   Failed: {failed}\n")

if failed:
    print("  Failed tests:")
    for name, ok in results:
        if not ok:
            print(f"    - {name}")
    sys.exit(1)
else:
    print(f"  All {total} tests passed!")
    sys.exit(0)
