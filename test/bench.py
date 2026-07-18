"""
Quality benchmark for myproxypool — run from OUTSIDE the container.

What it does
------------
For each pool (cn / intl):
  1. GET /all?pool=<p>&protocol=http   — sample N proxies
  2. Concurrently use each proxy to fetch the corresponding target:
        cn   -> http://www.eastmoney.com   (looks for eastmoney marker)
        intl -> http://api.ipify.org       (looks for IPv4)
  3. Report success rate, median/p95 ping, failure breakdown, top sources.

This measures REAL consumer-side success rate. The pool's internal /stats
counts proxies that pass its own validator; that is not the same as
"proxies a downstream caller can use right now".

Usage
-----
    python test/bench.py
    python test/bench.py --n 50 --pool cn
    python test/bench.py --api http://prod-host:12563 --n 100 --workers 32
"""
import argparse
import json
import random
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

DEFAULT_API = "http://localhost:12563"

POOL_TARGETS = {
    "cn":   ("http://www.eastmoney.com", lambda b: ("东方财富" in b) or ("eastmoney" in b.lower())),
    "intl": ("http://api.ipify.org",     lambda b: bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", b.strip()))),
}

def http_json(url: str, timeout: int):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())

def try_proxy(proxy: dict, target: str, verify, timeout: int) -> dict:
    proxy_url = f"http://{proxy['host']}:{proxy['port']}"
    handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    opener = urllib.request.build_opener(handler)
    start = time.monotonic()
    try:
        with opener.open(target, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="ignore")
            elapsed = int((time.monotonic() - start) * 1000)
            ok = (r.status == 200) and verify(body)
            return {"proxy": proxy, "ok": ok, "ping": elapsed,
                    "err": "" if ok else f"status={r.status} or verify_failed"}
    except urllib.error.HTTPError as e:
        return {"proxy": proxy, "ok": False, "ping": 0, "err": f"HTTP {e.code}"}
    except urllib.error.URLError as e:
        return {"proxy": proxy, "ok": False, "ping": 0, "err": f"URL {e.reason}"}
    except Exception as e:
        return {"proxy": proxy, "ok": False, "ping": 0, "err": type(e).__name__}

def bench_pool(api: str, pool: str, n: int, workers: int, timeout: int) -> None:
    print(f"\n=== pool={pool} ===")
    target, verify = POOL_TARGETS[pool]
    try:
        proxies = http_json(f"{api}/all?pool={pool}&protocol=http", timeout)
    except Exception as e:
        print(f"  /all failed: {e}")
        return
    if not proxies:
        print("  pool empty, skip")
        return

    sample = random.sample(proxies, min(n, len(proxies)))
    print(f"  sampled {len(sample)} of {len(proxies)} http proxies; target {target}")

    started = time.monotonic()
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(try_proxy, p, target, verify, timeout) for p in sample]
        for f in as_completed(futs):
            results.append(f.result())
    elapsed = time.monotonic() - started

    ok = [r for r in results if r["ok"]]
    pings = [r["ping"] for r in ok]
    rate = len(ok) / len(results) * 100 if results else 0

    print(f"  duration: {elapsed:.1f}s")
    print(f"  success:  {len(ok)}/{len(results)}  ({rate:.1f}%)")
    if pings:
        print(f"  ping ms:  median={int(statistics.median(pings))}  "
              f"p95={int(_p95(pings))}  min={min(pings)}  max={max(pings)}")

    err_breakdown: dict[str, int] = {}
    for r in results:
        if not r["ok"]:
            err_breakdown[r["err"]] = err_breakdown.get(r["err"], 0) + 1
    if err_breakdown:
        print("  failures:")
        for err, count in sorted(err_breakdown.items(), key=lambda x: -x[1]):
            print(f"    {count:>4}  {err}")

    src_breakdown: dict[str, list[int]] = {}
    for r in results:
        s = r["proxy"].get("source", "unknown")
        src_breakdown.setdefault(s, [0, 0])
        src_breakdown[s][0] += 1 if r["ok"] else 0
        src_breakdown[s][1] += 1
    print("  by source:")
    for s, (good, total) in sorted(src_breakdown.items(), key=lambda x: -x[1][1]):
        print(f"    {s:<18} {good:>3}/{total:<3}  ({good/total*100:5.1f}%)")

def _p95(values: list[int]) -> float:
    s = sorted(values)
    if not s:
        return 0
    k = max(0, int(len(s) * 0.95) - 1)
    return s[k]

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=DEFAULT_API)
    ap.add_argument("--n", type=int, default=30, help="sample size per pool")
    ap.add_argument("--pool", choices=["cn", "intl", "both"], default="both")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--timeout", type=int, default=10)
    args = ap.parse_args()

    print(f"API: {args.api}  workers={args.workers}  timeout={args.timeout}s")
    pools = ["cn", "intl"] if args.pool == "both" else [args.pool]
    for p in pools:
        bench_pool(args.api, p, args.n, args.workers, args.timeout)
    return 0

if __name__ == "__main__":
    sys.exit(main())
