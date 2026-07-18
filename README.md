#  Xproxypool Gateway — Self-Hosted Rotating Proxy Pool

> **Your own residential proxy network.** Auto-fetch from 28 sources, validate, score, and expose a single rotating endpoint with auth. One command, zero dependencies on third-party proxy services.

[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue)](https://python.org)
[![Stars](https://img.shields.io/github/stars/yourusername/xproxypool-gateway?style=social)](https://github.com/yourusername/xproxypool-gateway)

---

##  What is this?

A complete **proxy pool + rotating gateway** that gives you a single `host:port:user:pass` endpoint. Every request through it gets a different IP — just like commercial residential proxy services, but self-hosted and free.

```
┌─────────────────────────────────────────────────────────┐
│                     YOUR TOOLS                           │
│  Browser / Scraper / Bot / curl / Proxifier             │
│         │                                                │
│         │  YOUR_SERVER_IP:32002:user:pass                │
│         ▼                                                │
│  ┌──────────────────────────────────────────┐           │
│  │        ROTATING GATEWAY                  │           │
│  │  SOCKS5 + HTTP auto-detect               │           │
│  │  Auth + Round-robin + 3x failover        │           │
│  │  200 proxy cache | refill every 30s      │           │
│  └──────────────┬───────────────────────────┘           │
│                 │                                        │
│  ┌──────────────▼───────────────────────────┐           │
│  │           XPROXYPOOL                     │           │
│  │  28 fetchers | Redis | Scoring system    │           │
│  │  Auto-fetch every 30min                  │           │
│  │  Auto-revalidate every 5min              │           │
│  │  1,500+ working proxies                  │           │
│  └──────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────┘
```

---

##  Features

| Feature | Description |
|---------|-------------|
|  **Auto-rotation** | Every request = different IP. No code changes needed |
|  **Failover** | Dead proxy? Auto-retry up to 3 different proxies (< 2s) |
|  **28 Sources** | Auto-scrapes free proxy lists + GitHub aggregators |
|  **Scoring System** | Proxies scored 0-100. High score = reliable, gets priority |
|  **Dual Pool** | CN pool (validated vs eastmoney) + INTL pool (validated vs ipify) |
|  **Auth** | SOCKS5 RFC 1929 + HTTP Basic auth. `host:port:user:pass` format |
|  **Auto-detect** | Single port handles both SOCKS5 and HTTP clients |
|  **Self-hosted** | No third-party service. Your server, your proxies |
|  **Docker Ready** | One `docker compose up -d` for the pool |

---

##  Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/yourusername/xproxypool-gateway.git
cd xproxypool-gateway

# Docker (recommended)
docker compose up -d

# OR native
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
redis-server --daemonize yes
python3 src/main.py
```

### 2. Start the Gateway

```bash
# Generate random credentials
USER="u$(openssl rand -hex 4)"
PASS="$(openssl rand -hex 12)"

# Start gateway (SOCKS5 + HTTP on port 32002)
python3 -m gateway.main \
  --username "$USER" \
  --password "$PASS" \
  --min-score 50 \
  --pool-size 200
```

### 3. Use It

```
# Format:  host:port:user:pass
YOUR_SERVER_IP:32002:USERNAME:PASSWORD
```

| Tool | How to use |
|------|-----------|
| **curl** | `curl -x socks5://user:pass@host:32002 http://api.ipify.org` |
| **Browser** | Set SOCKS5 proxy → host:32002 → enter user/pass |
| **Proxifier** | Add proxy → Type SOCKS5 → host / 32002 / user / pass |
| **Python** | Use `aiohttp-socks` with `ProxyConnector.from_url()` |
| **proxychains** | `socks5 host 32002 user pass` |

---

##  Architecture

```
xproxypool-gateway/
├── src/
│   ├── proxy_pool/          # Xproxypool — proxy pool engine
│   │   ├── core/
│   │   │   ├── scheduler.py # 3 cron jobs (fetch, validate, recheck)
│   │   │   ├── storage.py   # Redis backend + Lua atomic ops
│   │   │   └── validator.py # Dual-target validation (eastmoney/ipify)
│   │   ├── fetchers/
│   │   │   ├── domestic.py  # 6 Chinese sources (HTML tables)
│   │   │   ├── international.py # 22 global sources (GitHub + APIs)
│   │   │   └── base.py      # Base fetcher (HTML/JSON parsers)
│   │   ├── api/routes.py    # REST API (/get, /stats, /all, /delete)
│   │   ├── schemas/proxy.py # Proxy model (Pydantic)
│   │   └── utils/
│   │
│   └── gateway/             #  Rotating Gateway (NEW)
│       ├── pool.py           # PoolManager — caches proxies from Xproxypool
│       ├── rotator.py        # Rotator — selection + 3x retry failover
│       ├── socks5.py         # SOCKS5 server + HTTP auto-detect + auth
│       ├── http_proxy.py     # HTTP forward proxy + CONNECT tunnel
│       └── main.py           # CLI entry point
│
├── sources.yml               # 28 proxy source configurations
├── docker-compose.yml        # Docker deployment
└── pyproject.toml
```

---

##  Proxy Sources (28 total)

### 🇨🇳 Domestic (6) — Chinese IPs
| Source | Type | Method |
|--------|------|--------|
| kuaidaili.com | HTTP | HTML table |
| ip3366.net | HTTP | HTML table |
| kxdaili.com | HTTP | HTML table |
| 89ip.cn | HTTP | Text |
| docip.net | HTTP | JSON API |
| zdaye.com | HTTP | HTML (disabled) |

###  International (22) — Global IPs
| Source | Protocols | Method |
|--------|-----------|--------|
| **proxyscrape.com** | HTTP, SOCKS5 | Text API |
| **geonode.com** | HTTP, SOCKS4/5 | JSON API |
| **TheSpeedX** (GitHub) | HTTP, SOCKS4/5 | Raw text |
| **monosans** (GitHub) | HTTP, SOCKS5 | Raw text |
| **proxifly** (CDN) | HTTP, SOCKS4/5 | Raw text |
| **vakhov** (GitHub) | HTTP, HTTPS, SOCKS4/5 | Raw text |
| **MuRongPIG** (GitHub) | HTTP, SOCKS4/5 | Raw text |
| **VMHeaven** (GitHub) | HTTP, HTTPS, SOCKS4/5 | Raw text |
| **ErcinDedeoglu** (GitHub) | HTTP, HTTPS, SOCKS4/5 | Raw text |
| **zevtyardt** (GitHub) | HTTP, SOCKS4/5 | Raw text |
| **hideip** (GitHub) | HTTP, HTTPS, SOCKS4/5 | Raw text |
| **mmpx12** (GitHub) | HTTP, HTTPS, SOCKS4/5 | Raw text |
| **komutan234** (GitHub) | HTTP, SOCKS4/5 | Raw text |
| **iplocate** (GitHub) | HTTP, HTTPS, SOCKS4/5 | Raw text |
| **kangproxy** (GitHub) | HTTP, HTTPS, SOCKS4 | Raw text |
| **openproxylist** | HTTP | Text API |
| 🆕 **roundproxies** | HTTP, SOCKS4/5 | JSON API |
| 🆕 **freevpnnode** | HTTP, SOCKS4/5 | HTML table |
| 🆕 **sslproxies.org** | HTTP | HTML table |
| 🆕 **us-proxy.org** | HTTP | HTML table |
| 🆕 **free-proxy-list.net** | HTTP | HTML table |

---

##  Proxy Lifecycle

```
NEW (from 28 fetchers)
  │
  ▼
VALIDATE (ipify.org / eastmoney.com)
  ├── PASS → SUCCESS pool (score=50)
  │            │
  │            ▼ (every 5min)
  │           RE-VALIDATE
  │            ├── PASS → score += 10 (max 100)
  │            └── FAIL → score -= 20
  │                        │
  │                        ▼ (score ≤ 0)
  │                      RECHECK pool
  │                        │
  │                        ▼ (every 15min)
  │                       RE-VALIDATE
  │                        ├── PASS → back to SUCCESS (score reset)
  │                        └── FAIL → DELETE permanently
  └── FAIL → discarded
```

---

##  Gateway Selection Logic

```
Local pool: 200 proxies

70% of the time: Pick from top ⅓ (lowest failures, highest score)
30% of the time: Explore new proxies (discover fresh ones)

Dead proxy → failures += 1
3 failures   → removed from local pool
Successful   → failures = 0 (trust restored)

Pool < 200   → auto-refill from Xproxypool every 30s
```

---

##  API Endpoints (Xproxypool)

```bash
# Get one random proxy
GET /get?pool=intl&min_score=60&protocol=socks5

# Get plain text format
GET /get?pool=intl&format=text
# → http://1.2.3.4:8080

# Get all proxies in pool
GET /all?pool=intl

# Pool statistics
GET /stats
# → {"intl": {"success": 1582, "recheck": 382, "avg_score": 74.3, ...}}

# Delete a proxy
DELETE /delete?proxy=1.2.3.4:8080&pool=intl
```

---

##  Configuration

All settings via environment variables or `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | localhost | Redis host |
| `REDIS_PORT` | 6379 | Redis port |
| `API_PORT` | 12563 | Xproxypool API port |
| `FETCH_INTERVAL` | 30 | Minutes between proxy fetches |
| `VALIDATE_INTERVAL` | 5 | Minutes between success revalidation |
| `RECHECK_INTERVAL` | 15 | Minutes between recheck validation |
| `SCORE_INIT` | 50 | Initial score for new proxies |
| `SCORE_INCREMENT` | 10 | Score gain on successful recheck |
| `SCORE_DECREMENT` | 20 | Score loss on failed recheck |
| `CN_PROXY_CAP` | 1000 | Max Chinese proxies in pool |
| `INTL_PROXY_CAP` | 2000 | Max international proxies in pool |
| `VALIDATOR_CONCURRENCY` | 50 | Concurrent validation workers |

### Gateway CLI

```bash
python3 -m gateway.main \
  --http-port 32001 \        # HTTP proxy port
  --socks5-port 32002 \      # SOCKS5 proxy port (also handles HTTP)
  --pool-api http://localhost:12563 \  # Xproxypool API
  --pool-name intl \         # Pool: cn or intl
  --min-score 50 \           # Minimum proxy score
  --max-retries 3 \          # Failover retry count
  --connect-timeout 8 \      # Upstream connect timeout (seconds)
  --pool-size 200 \          # Local cache size
  --refill-interval 30 \     # Refill interval (seconds)
  --username USERNAME \     #  Proxy auth username
  --password  \     #  Proxy auth password
  --http-only \              # HTTP proxy only (no SOCKS5)
  --socks5-only              # SOCKS5 proxy only (no HTTP)
```

---

##  Performance

| Metric | Value |
|--------|-------|
| Success rate (client-facing) | **~92%** |
| Gateway first-attempt rate | ~44% |
| Failover recovery rate | 56% (3 retries covers most failures) |
| Unique IPs per 3-minute window | **20-27** |
| Pool size (steady state) | 1,500-2,000 |
| Avg proxy score | 65-75 |
| Proxy churn rate | ~30% per hour (free proxies die fast) |

---

##  Limitations

- **Free proxies are unreliable.** Expect 60-80% of fetched proxies to be dead. The scoring system + failover handles this, but success rate won't reach 100%.
- **SOCKS5 proxies are rare.** Most free proxies are HTTP-only. SOCKS5 availability is ~5-10% of the pool.
- **CN pool stays empty.** Free proxy lists are 99% non-Chinese IPs. For Chinese IPs, you need paid sources or custom imports.
- **No built-in dashboard.** The gateway exposes a REST API but no web UI (yet).

---

##  Contributing

1. Fork the repo
2. Add new fetchers in `src/proxy_pool/fetchers/` (see existing patterns)
3. Add source config in `sources.yml`
4. Register in `__init__.py` → `ALL_FETCHERS`
5. PR

---

##  Credits

- **Original Xproxypool**: [yehx6/Xproxypool](https://github.com/yehx6/Xproxypool) — proxy pool engine
- **Gateway + Auth + 5 sources**: BREACH v6 + Aroshi (2026)
- **28 proxy sources**: compiled from jhao104/proxy_pool, Spoon, yukkcat/socks5-proxy, and others

---

##  License

MIT — do whatever you want. Just don't blame us if you do illegal shit.
