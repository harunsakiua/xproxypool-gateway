"""
End-to-end smoke test for myproxypool — run from OUTSIDE the container.

What it does
------------
1. GET /stats           — both pools must have success > 0
2. GET /get?pool=cn     — pick an http proxy, use it to fetch eastmoney.com
3. GET /get?pool=intl   — pick an http proxy, use it to fetch api.ipify.org

Exit code: 0 = all pass, 1 = any failure.

Usage
-----
    python test/smoke.py
    python test/smoke.py --api http://localhost:12563
    python test/smoke.py --api http://prod-host:12563 --timeout 20
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request

DEFAULT_API = "http://localhost:12563"

def http_json(url: str, timeout: int) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())

def fetch_via_proxy(target: str, proxy_url: str, timeout: int) -> tuple[int, str]:
    handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    opener = urllib.request.build_opener(handler)
    with opener.open(target, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", errors="ignore")

_failed = 0

def check(name: str, ok: bool, detail: str = "") -> None:
    global _failed
    if ok:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))
        _failed += 1

def section(title: str) -> None:
    print(f"\n--- {title} ---")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=DEFAULT_API)
    ap.add_argument("--timeout", type=int, default=15)
    args = ap.parse_args()

    print(f"API: {args.api}")

    # -------------------------------------------------- 1. /stats
    section("1. /stats")
    try:
        stats = http_json(f"{args.api}/stats", args.timeout)
    except Exception as e:
        check("/stats reachable", False, str(e))
        return 1
    cn_n = stats.get("cn", {}).get("success", 0)
    intl_n = stats.get("intl", {}).get("success", 0)
    print(f"  cn.success = {cn_n},  intl.success = {intl_n}")
    check("cn pool has at least 1 proxy", cn_n > 0)
    check("intl pool has at least 1 proxy", intl_n > 0)

    # -------------------------------------------------- 2. cn → eastmoney
    section("2. cn pool -> eastmoney.com")
    if cn_n == 0:
        check("cn pool reachable", False, "skip: pool empty")
    else:
        try:
            cn = http_json(f"{args.api}/get?pool=cn&protocol=http", args.timeout)
            proxy_url = f"http://{cn['host']}:{cn['port']}"
            print(f"  using {proxy_url}  score={cn['score']}  region={cn.get('region','-')}")
            status, body = fetch_via_proxy("http://www.eastmoney.com", proxy_url, args.timeout)
            check("HTTP 200", status == 200, f"status={status}")
            check(
                "response contains eastmoney marker",
                ("东方财富" in body) or ("eastmoney" in body.lower()),
                f"body[:80]={body[:80]!r}",
            )
        except urllib.error.HTTPError as e:
            check("/get?pool=cn returns a proxy", False, f"{e.code} {e.reason}")
        except Exception as e:
            check("cn proxy usable", False, repr(e))

    # -------------------------------------------------- 3. intl → ipify
    section("3. intl pool -> api.ipify.org")
    if intl_n == 0:
        check("intl pool reachable", False, "skip: pool empty")
    else:
        try:
            intl = http_json(f"{args.api}/get?pool=intl&protocol=http", args.timeout)
            proxy_url = f"http://{intl['host']}:{intl['port']}"
            print(f"  using {proxy_url}  score={intl['score']}  region={intl.get('region','-')}")
            status, body = fetch_via_proxy("http://api.ipify.org", proxy_url, args.timeout)
            check("HTTP 200", status == 200, f"status={status}")
            check(
                "response is an IPv4 address",
                bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", body.strip())),
                f"body={body[:80]!r}",
            )
        except urllib.error.HTTPError as e:
            check("/get?pool=intl returns a proxy", False, f"{e.code} {e.reason}")
        except Exception as e:
            check("intl proxy usable", False, repr(e))

    # -------------------------------------------------- summary
    print()
    if _failed == 0:
        print("ALL PASS")
        return 0
    print(f"FAILED: {_failed} check(s)")
    return 1

if __name__ == "__main__":
    sys.exit(main())
