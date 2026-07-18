# Xproxypool

[简体中文](README.md) | **English**

[![CI](https://github.com/yehx6/Xproxypool/actions/workflows/ci.yml/badge.svg)](https://github.com/yehx6/Xproxypool/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/yehx6/Xproxypool)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688.svg)](https://fastapi.tiangolo.com)
[![Redis](https://img.shields.io/badge/redis-DC382D.svg?logo=redis&logoColor=white)](https://redis.io)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com)
[![Last Commit](https://img.shields.io/github/last-commit/yehx6/Xproxypool)](https://github.com/yehx6/Xproxypool/commits/main)
[![Stars](https://img.shields.io/github/stars/yehx6/Xproxypool?style=social)](https://github.com/yehx6/Xproxypool/stargazers)

> A self-running free proxy pool service with **built-in scraping, automatic validation, and geo-aware pool routing**.
> Deploy once, and your application has a stable HTTP endpoint to grab fresh proxy IPs on demand.

---

## What you get

If your code has this kind of need:

```python
# Want to rotate IPs without scraping the web yourself every day
requests.get("https://target.com", proxies={"http": "???", "https": "???"})
```

After deploying Xproxypool, the line becomes:

```python
# Grab a domestic (CN) proxy — default pool
proxy = httpx.get("http://localhost:12563/get").json()
url = f"http://{proxy['host']}:{proxy['port']}"
requests.get("https://target.com", proxies={"http": url, "https": url})

# Want an international proxy? Add one parameter
proxy = httpx.get("http://localhost:12563/get?pool=intl").json()
```

You **get**:

- **A 24/7 service** — scrapes, validates, and evicts dead proxies on its own
- **Two independent pools** — `cn` validated against domestic targets, `intl` against overseas targets, 1000 each by default
- **An HTTP API** — one `curl` to `GET /get` returns a working proxy
- **A scoring system** — fast, stable proxies are prioritized (score 0–100)
- **Geolocation metadata** — every proxy carries country / province / ISP info
- **Full observability** — `/stats` shows live pool health; logs detail every validation

---

## Core capabilities

| Capability | Detail |
|---|---|
| **Multi-source scraping** | 22 public proxy sources (6 domestic Chinese sites + 16 international GitHub-hosted lists), hot-reloadable YAML |
| **Dual-pool architecture** | `cn` pool tests `eastmoney.com`, `intl` pool tests `api.ipify.org`, each with its own target and capacity |
| **Full protocol support** | HTTP / HTTPS / SOCKS4 / SOCKS5 from a single API |
| **Geo-routing** | Built-in offline `ip2region.xdb` library; new proxies route into the correct pool by IP origin |
| **Three-state lifecycle** | success → recheck → permanent delete; junk proxies retire automatically |
| **Score-based eviction** | Default init=50, +10 on pass (max 100), -30 on fail; sub-zero score moves to recheck |
| **Capacity bounds** | cn / intl default to 1000 each; Lua scripts guarantee no overflow under high concurrency |
| **Zero-friction deployment** | One `docker compose up -d` boots the entire stack |

---

## Quick start

### 1. Boot

```bash
git clone <repo> && cd Xproxypool
docker compose up -d
```

After boot:
- API listens on `http://localhost:12563`
- Redis exposed on `127.0.0.1:6380` (host port; container side stays at 6379)

The first run triggers an immediate fetch in the background. **In about 2–5 minutes** both pools have data ready to use.

### 2. Call

```bash
# Pool health
curl http://localhost:12563/stats

# Grab a domestic http proxy
curl http://localhost:12563/get?pool=cn

# Grab an international socks5 proxy in plain text (pipe straight into curl --proxy)
curl 'http://localhost:12563/get?pool=intl&protocol=socks5&format=text'
```

### 3. Verify it actually works

The repo ships two **out-of-container** test scripts (Python stdlib only, **zero deps**):

```bash
# Smoke: 30 seconds, tells you "works / doesn't"
python test/smoke.py

# Benchmark: 1-2 minutes, tells you "real success rate / which source is best"
python test/bench.py --n 30
```

See [Testing & quality validation](#testing--quality-validation) below.

---

## API reference

Service port: `12563` (overridable via `API_PORT` in `.env`).

### `GET /get` — fetch one proxy

| Param | Default | Description |
|---|---|---|
| `pool` | `cn` | `cn` or `intl` |
| `protocol` | any | `http` / `https` / `socks4` / `socks5`; omit for any protocol |
| `min_score` | `50` | Only return proxies with score ≥ this |
| `format` | JSON | Set to `text` for plain `protocol://host:port` |

Sample response:
```json
{
  "host": "106.15.137.41",
  "port": 50,
  "protocol": "http",
  "score": 100,
  "ping": 412,
  "source": "vmheaven",
  "anonymous": true,
  "region": "中国|0|上海|上海市|电信",
  "created_at": "2026-04-27 02:38:11",
  "last_check": "2026-04-27 02:48:09"
}
```

Returns **404** when no proxy matches.

### `GET /all` — return the full pool

```bash
curl 'http://localhost:12563/all?pool=cn&protocol=http'
```
Returns an array — useful for batch processing or sampling.

### `GET /stats` — pool statistics

```json
{
  "cn":   {"success": 1000, "recheck": 876, "avg_score": 44.8,
           "sources": {"vmheaven": 746, "murongpig": 116, ...}},
  "intl": {"success": 1000, "recheck": 14,  "avg_score": 97.8,
           "sources": {...}}
}
```

### `DELETE /delete` — manually evict

```bash
curl -X DELETE 'http://localhost:12563/delete?pool=cn&proxy=1.2.3.4:8080'
```

---

## Testing & quality validation

**All tests run outside the container** — by design. Consumers live outside the container, so tests should sit on the consumer side, using the same HTTP client (`urllib + ProxyHandler`) as production code.

### `test/smoke.py` — deployment smoke test

In five steps, tells you whether the full pipeline works:

```bash
$ python test/smoke.py
API: http://localhost:12563

--- 1. /stats ---
  PASS  cn pool has at least 1 proxy
  PASS  intl pool has at least 1 proxy

--- 2. cn pool -> eastmoney.com ---
  using http://106.15.137.41:50  score=100
  PASS  HTTP 200
  PASS  response contains eastmoney marker

--- 3. intl pool -> api.ipify.org ---
  using http://206.238.239.5:80  score=100
  PASS  HTTP 200
  PASS  response is an IPv4 address

ALL PASS
```

Exit code `0` / `1` — drop straight into CI or cron monitoring.

### `test/bench.py` — real-success-rate benchmark

Random-samples N proxies, hits real targets, and gives you a **consumer-side** quality report:

```bash
$ python test/bench.py --n 30 --workers 16

=== pool=cn ===
  sampled 30 of 1000 http proxies; target http://www.eastmoney.com
  success:  18/30  (60.0%)
  ping ms:  median=1812  p95=2266  min=411  max=2845
  failures:
       6  URL Tunnel connection failed: 400 Bad Request
       4  TimeoutError
       2  URL Tunnel connection failed: 405 Method Not Allowed
  by source:
    vmheaven             14/16  ( 87.5%)
    openproxylist         3/8   ( 37.5%)
    89ip                  0/4   (  0.0%)    ← disable this source
    thespeedx             1/2   ( 50.0%)

=== pool=intl ===
  success:  29/30  (96.7%)
  ping ms:  median=441  p95=712  min=287  max=890
  by source:
    murongpig            22/22  (100.0%)
    proxyscrape           4/4   (100.0%)
    ...
```

**The "real success rate" reported by bench is usually lower than the success counter in `/stats`**, because bench drives `urllib` over an HTTPS CONNECT tunnel (the actual consumer path) while the in-container validator only does an HTTP GET (more lenient). Closing that gap is exactly what bench is for.

### Test script overview

| File | Purpose | Needs deployment? |
|---|---|---|
| `test/smoke.py` | One-shot post-deploy sanity check | Yes |
| `test/bench.py` | Quantify real pool quality, broken down by source | Yes |
| `src/proxy_pool/tests/run_tests.py` | In-container self-check (55 assertions, code-level) | No (standalone) |

---

## Configuration

Most-tweaked knobs — edit `.env`, then `docker compose restart`:

| Variable | Default | Why touch it |
|---|---|---|
| `CN_PROXY_CAP` / `INTL_PROXY_CAP` | `1000` | Bigger pools = wider coverage but slower validation cycles. 100–5000 are all sane. |
| `FETCH_INTERVAL` | `20` (min) | Fetch auto-skips when full; setting this below validate is pointless |
| `VALIDATE_INTERVAL` | `10` | Lower = fresher proxies but more requests to the verification target |
| `SCORE_INIT` / `SCORE_DECREMENT` | `50` / `30` | Must satisfy `INIT >= DECREMENT`, or proxies die after a single failure (we hit this bug in early dev) |
| `VALIDATOR_CONCURRENCY` | `50` | Higher = faster validation but heavier socket pressure on the host |

**Source toggles** live in `sources.yml` — flip `enabled: false` on anything you don't want. Sources at 0% in the bench report should be disabled.

---

## How it works

```
                  every 20 minutes
                        │
       ┌────────────────┴────────────────┐
       │  scrapers (22 sources, async)   │
       └────────────────┬────────────────┘
                        │ dedupe + skip already-known IPs
                        ▼
                ┌──────────────┐
                │  ip2region   │ ← offline geo DB
                │  route by GB │
                └─┬──────────┬─┘
        Chinese IP│          │ overseas IP
                  ▼          ▼
            hit eastmoney   hit ipify
                  │          │
        on pass → cn / intl pool (success)
                  │          │
       every 10  │          │
       min retest▼          ▼
            score ≤ 0 → move to recheck
                  │          │
       every 60  │          │
       min revive│          │
            pass → back to success (if not full)
            fail → permanent delete
```

---

## Project structure

```
Xproxypool/
├── src/                                 main project code
│   ├── main.py                          FastAPI entrypoint
│   ├── proxy_pool/
│   │   ├── api/                         HTTP endpoints
│   │   ├── core/                        scheduling / validation / Redis storage
│   │   ├── fetchers/                    22 source implementations
│   │   ├── schemas/                     Proxy model
│   │   ├── tests/run_tests.py           in-container self-check
│   │   └── utils/                       config / geo / logging
│   └── ip2region/                       offline geo library
│
├── test/                                out-of-container integration tests
│   ├── smoke.py                         deployment smoke
│   └── bench.py                         real-success-rate benchmark
│
├── sources.yml                          URL config for the 22 sources
├── ip2region.xdb                        offline geo database
├── pyproject.toml                       Python deps
├── Dockerfile / docker-compose.yml      deployment
└── .env                                 runtime config
```

---

## Use cases

- **Scraping / data collection** — batch `/get` to rotate IPs and bypass per-IP QPS limits or blocks
- **Multi-account workflows** — pin each account to a high-score sticky proxy
- **Cross-border reachability checks** — `/get?pool=intl` to verify overseas reachability
- **Network diversity testing** — test CDN behavior across Chinese provinces / ISPs (proxy region is precise to ISP level)
- **CI integration** — wire `smoke.py` into the pipeline, alert when the pool dies

---

## Extension guide

Every extension point lives under `src/`. Edit, then `docker compose restart myproxypool` — `src/` is mounted read-only, **no image rebuild needed**.

### 1. Add a new proxy source (most common)

Three steps: **write a fetcher class → register → configure the URL**.

**Step 1**: in `src/proxy_pool/fetchers/domestic.py` or `international.py`, add a class subclassing `BaseFetcher`. `get_html` / `get_json` already handle direct/proxy fallback, timeouts, encoding, and socket cleanup — you just write the parser:

```python
class MyFetcher(BaseFetcher):
    source = "myfetcher"   # unique id; lands in Proxy.source

    async def fetch(self) -> list[Proxy]:
        cfg = get("international", "myfetcher")  # read sources.yml
        if not cfg.get("enabled", True):
            return []

        # Three typical parsing patterns — pick one:

        # A) HTML table (column 1 = IP, column 2 = port)
        html = await self.get_html(cfg["url"])
        return self._parse_table(html, protocol="http")

        # B) plain-text "ip:port" lines (common for GitHub raw files)
        text = await self.get_html(cfg["url"])
        return self._parse_text(text, protocol="socks5")

        # C) JSON API — extract fields yourself
        data = await self.get_json(cfg["url"])
        return [
            Proxy(host=item["ip"], port=item["port"],
                  protocol=item.get("type", "http"), source=self.source)
            for item in data["proxies"]
        ]
```

**Step 2**: register the class in `src/proxy_pool/fetchers/__init__.py`'s `ALL_FETCHERS` list — only then will the scheduler pick it up:

```python
from proxy_pool.fetchers.international import MyFetcher  # add import

ALL_FETCHERS = [
    ...
    MyFetcher,                                            # append
]
```

**Step 3**: declare the URL in `sources.yml` at repo root:

```yaml
international:
  myfetcher:
    enabled: true
    url: "https://example.com/api/proxies?type=all"
```

`docker compose restart myproxypool` → the next `fetch_job` (within 20 min) will run your fetcher. To verify, watch for `MyFetcher fetched N proxies` in the logs.

### 2. Change / add validation targets

`src/proxy_pool/core/validator.py` near the top:

```python
CN_TARGET   = ("http://www.eastmoney.com", _verify_eastmoney)
INTL_TARGET = ("http://api.ipify.org",     _verify_ipify)
```

To swap (e.g. only care if proxies can reach your own service), change the URL and write a new `_verify_xxx`:

```python
async def _verify_mybusiness(resp: aiohttp.ClientResponse) -> bool:
    if resp.status != 200:
        return False
    body = await resp.text()
    return "expected-marker-string" in body

CN_TARGET = ("http://your-business-cn.com/healthz", _verify_mybusiness)
```

> **Important**: the target must be HTTP (not HTTPS), or the divergent CONNECT-tunnel paths between SOCKS and HTTP proxies will cause widespread false negatives on SOCKS proxies. To test HTTPS, write separate request paths for HTTP and SOCKS proxies.

### 3. Add a new API endpoint

`src/proxy_pool/api/routes.py` — same pattern as the existing endpoints. For example, "filter by region keyword":

```python
@router.get("/get_by_region")
async def get_by_region(
    keyword: str = Query(..., description="region substring, e.g. '上海' or 'United States'"),
    pool: PoolName = Query("cn"),
):
    proxies = await _get_pool(pool).get_success_list()
    matched = [p for p in proxies if keyword in p.region]
    if not matched:
        raise HTTPException(status_code=404, detail=f"No proxy in region containing {keyword!r}")
    import random
    return random.choice(matched).model_dump()
```

After `docker compose restart`, `curl 'http://localhost:12563/get_by_region?keyword=上海'` works.

### 4. Tune the scheduler

Two common presets, edit `.env`:

```bash
# Small pool, fast iteration
CN_PROXY_CAP=200
INTL_PROXY_CAP=200
VALIDATE_INTERVAL=5     # 5-min validation cycle, fresher proxies

# Large pool, broad coverage
CN_PROXY_CAP=5000
INTL_PROXY_CAP=5000
VALIDATOR_CONCURRENCY=200   # raise concurrency or a cycle won't finish
```

### 5. Plug into external monitoring

`/stats` is already structured JSON. Easiest Prometheus path: a sidecar that polls every minute and converts to metrics. Or just cron:

```bash
*/1 * * * * curl -s http://localhost:12563/stats | jq -c \
  '{ts: now, cn_success: .cn.success, cn_avg: .cn.avg_score, \
     intl_success: .intl.success, intl_avg: .intl.avg_score}' \
  >> /var/log/xproxypool-stats.jsonl
```

### 6. Drop garbage sources based on bench data

Run `python test/bench.py --n 100` periodically and inspect the `by source` block. Any source stuck in 0–20% range — flip it to `enabled: false` in `sources.yml`. **Pruning bad sources is the single most effective quality lever** — way more impactful than writing more fetchers.

### 7. Let an LLM inspect the pool directly (MCP)

The repo ships an MCP (Model Context Protocol) server in `mcp_server/` that
exposes the Redis state as read-only tools to any MCP-compatible client —
Claude Desktop / Claude Code / Cursor / Continue, etc.

Once mounted, you can ask in natural language:

- *"What's the current pool health?"* → model calls `pool_stats`, summarizes
- *"Why is cn avg_score so low?"* → `count_by_source` + `list_recheck`, identifies the worst source
- *"Give me a Shanghai-Telecom socks5 proxy"* → `list_proxies(protocol="socks5", region_contains="上海电信")`

7 read-only tools; no write operations are exposed, so the LLM can't
accidentally delete proxies. Configuration details in
[`mcp_server/README.md`](mcp_server/README.md).

### 8. Build an SDK for consumers (optional)

If you want a friendlier interface for the rest of the team, add a `client.py` under `test/` wrapping `/get` with retries:

```python
# test/client.py
import urllib.request, json, random

class XproxyClient:
    def __init__(self, api="http://localhost:12563"): self.api = api
    def get(self, pool="cn", protocol="http", retries=3):
        for _ in range(retries):
            try:
                r = urllib.request.urlopen(f"{self.api}/get?pool={pool}&protocol={protocol}", timeout=5)
                return json.loads(r.read())
            except Exception:
                continue
        return None

# consumer call site
client = XproxyClient()
proxy = client.get(pool="intl")
```

---

## Acknowledgements

- IP geolocation data: [lionsoul2014/ip2region](https://github.com/lionsoul2014/ip2region)
- Maintainers of the 22 public proxy sources (see `sources.yml`)

---

## License

[MIT License](LICENSE) — free to use, modify, and redistribute, including for commercial purposes.
