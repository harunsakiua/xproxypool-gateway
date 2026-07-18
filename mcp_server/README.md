# xproxypool-mcp

> An MCP (Model Context Protocol) server that lets any MCP-compatible LLM
> client — Claude Desktop, Claude Code, Cursor, Continue, etc. — inspect
> the running [Xproxypool](../README.md) Redis state in natural language.

You ask "为什么 cn 池 avg_score 这么低?" and the model has the tools to
actually go look — `pool_stats`, `count_by_source`, `list_recheck` —
instead of guessing.

---

## What it exposes

7 read-only tools. All operate on the live Redis at `127.0.0.1:6380` (the
host port the main `docker-compose.yml` exposes for the proxy pool).

| Tool | Purpose |
|---|---|
| `pool_stats` | Health overview — counts, avg score, source distribution for both pools |
| `random_proxy` | Pick one proxy with optional protocol / score filters |
| `list_proxies` | Filtered + sorted list (by score / ping / created_at / last_check) |
| `proxy_detail` | Full record for a specific `host:port`, including which pool/state |
| `count_by_source` | Per-fetcher quality breakdown — count, avg score, avg ping |
| `count_by_region` | Top-N regions by proxy count (drives geo-routing analysis) |
| `list_recheck` | Proxies one validation away from deletion — diagnose failing sources |

Write operations (delete, score adjustment) are deliberately **not exposed** —
this is an inspection layer, not a remote control.

---

## Install

Requires Python 3.11+ and a running Redis (typically the one started by the
parent project's `docker compose up -d`).

```bash
cd mcp_server
pip install -e .
```

This installs an `xproxypool-mcp` script and the `xproxypool_mcp` package.

---

## Configure your MCP client

The server speaks **stdio**, so the client just needs a command + args.

### Claude Code

Project-level config — create `.mcp.json` in your repo root:

```json
{
  "mcpServers": {
    "xproxypool": {
      "command": "xproxypool-mcp"
    }
  }
}
```

If `xproxypool-mcp` is not on PATH (common with venv installs), use the
absolute path:

```json
{
  "mcpServers": {
    "xproxypool": {
      "command": "C:/path/to/your/.venv/Scripts/python.exe",
      "args": ["-m", "xproxypool_mcp.server"]
    }
  }
}
```

Restart Claude Code, then `/mcp` should list the `xproxypool` server with 7 tools.

### Claude Desktop

Edit `claude_desktop_config.json`
(`%APPDATA%\Claude\claude_desktop_config.json` on Windows,
`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "xproxypool": {
      "command": "C:/path/to/your/.venv/Scripts/python.exe",
      "args": ["-m", "xproxypool_mcp.server"],
      "env": {
        "XPROXYPOOL_REDIS_HOST": "127.0.0.1",
        "XPROXYPOOL_REDIS_PORT": "6380"
      }
    }
  }
}
```

Restart Claude Desktop, then look for the tool icon (🔧) in the chat
input — tools from `xproxypool` should be listed.

### Cursor

Settings → MCP → Add new MCP server, with the same `command` + `args`
format as Claude Code above.

---

## Custom Redis target

If your Redis is somewhere else (different host/port, password, non-zero DB),
set environment variables in your client's MCP config:

| Env var | Default |
|---|---|
| `XPROXYPOOL_REDIS_HOST` | `127.0.0.1` |
| `XPROXYPOOL_REDIS_PORT` | `6380` |
| `XPROXYPOOL_REDIS_DB` | `0` |
| `XPROXYPOOL_REDIS_PASSWORD` | (empty) |

---

## Example queries

Once mounted, just ask in natural language:

- *"What's the current pool health?"*
  → Model calls `pool_stats`, summarizes both pools.

- *"我想要一个上海电信的 socks5 代理"*
  → `list_proxies(pool="cn", protocol="socks5", region_contains="上海电信")`.

- *"Why is cn avg_score so low? Which source is the worst?"*
  → `count_by_source(pool="cn")` → identifies the lowest-scoring source,
    cross-references with `list_recheck(pool="cn")` for confirmation.

- *"Show me the 5 fastest intl proxies."*
  → `list_proxies(pool="intl", sort_by="ping", limit=5)`.

- *"How many proxies are from California?"*
  → `count_by_region(pool="intl")` then filters California from the result,
    or `list_proxies(region_contains="California", limit=100)`.

- *"Look up `1.2.3.4:8080` — is it healthy?"*
  → `proxy_detail("1.2.3.4:8080", pool="cn")` returns score, ping, last_check,
    and which pool/state it's in.

---

## Troubleshooting

**`ConnectionRefusedError` on first call**
The proxy pool isn't running, or the Redis port mapping changed. Check:
```bash
docker compose ps
docker compose port redis 6379    # should output "0.0.0.0:6380"
```

**Tools list is empty in the client**
The MCP server failed to start. Run it manually to see the error:
```bash
xproxypool-mcp
# or
python -m xproxypool_mcp.server
```
It should hang silently waiting for stdio input — Ctrl+C to exit. If it
errors out, the message is the diagnostic.

**`pool_stats` returns 0 success counts**
The pool just started and hasn't done its first validation yet (~2-5 min
after `docker compose up -d`).
