"""
ROTATING PROXY GATEWAY — Main Entry Point
Starts HTTP + SOCKS5 proxy servers with rotating upstream pool.

Usage:
    python -m gateway.main
    python -m gateway.main --http-port 32001 --socks5-port 32002
    python -m gateway.main --pool-api http://localhost:12563 --min-score 60
"""
import argparse
import asyncio
import logging
import signal
import sys

from .http_proxy import HTTPProxyServer
from .pool import PoolManager
from .rotator import Rotator
from .socks5 import SOCKS5ProxyServer

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # DEBUG biar keliatan semua
    format="%(asctime)s | %(name)-18s | %(levelname)-5s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/home/ubuntu/xproxypool/logs/gateway.log", mode="a"),
    ],
)
logger = logging.getLogger("gateway")


async def main():
    parser = argparse.ArgumentParser(description="BREACH Rotating Proxy Gateway")
    parser.add_argument("--http-port", type=int, default=32001, help="HTTP proxy port")
    parser.add_argument(
        "--socks5-port", type=int, default=32002, help="SOCKS5 proxy port"
    )
    parser.add_argument(
        "--pool-api",
        default="http://localhost:12563",
        help="Xproxypool API URL",
    )
    parser.add_argument(
        "--pool-name", default="intl", help="Pool name: cn or intl"
    )
    parser.add_argument(
        "--min-score", type=int, default=50, help="Minimum proxy score"
    )
    parser.add_argument(
        "--max-retries", type=int, default=3, help="Max failover retries"
    )
    parser.add_argument(
        "--connect-timeout", type=int, default=8, help="Upstream connect timeout (s)"
    )
    parser.add_argument(
        "--pool-size", type=int, default=100, help="Local pool max size"
    )
    parser.add_argument(
        "--refill-interval", type=int, default=30, help="Pool refill interval (s)"
    )
    parser.add_argument(
        "--http-only", action="store_true", help="Start HTTP proxy only"
    )
    parser.add_argument(
        "--socks5-only", action="store_true", help="Start SOCKS5 proxy only"
    )
    parser.add_argument(
        "--username", default="", help="Proxy auth username (empty = no auth)"
    )
    parser.add_argument(
        "--password", default="", help="Proxy auth password (empty = no auth)"
    )
    args = parser.parse_args()

    # --- Banner ---
    print(
        """
╔══════════════════════════════════════════════════════════╗
║        BREACH ROTATING PROXY GATEWAY v1.0               ║
║        Auto-rotate • Failover • Self-healing            ║
╚══════════════════════════════════════════════════════════╝
"""
    )

    # --- Pool Manager ---
    pool = PoolManager(
        api_url=args.pool_api,
        pool_name=args.pool_name,
        min_score=args.min_score,
        max_size=args.pool_size,
        refill_interval=args.refill_interval,
    )
    await pool.start()
    logger.info(
        f"PoolManager: {args.pool_name} pool, "
        f"min_score={args.min_score}, max_size={args.pool_size}"
    )

    # --- Rotator ---
    rotator = Rotator(
        pool=pool,
        max_retries=args.max_retries,
        connect_timeout=args.connect_timeout,
    )

    # --- Proxy Servers ---
    servers = []

    if not args.socks5_only:
        http_server = HTTPProxyServer(
            rotator=rotator, host="0.0.0.0", port=args.http_port,
            username=args.username, password=args.password,
        )
        servers.append(("HTTP", args.http_port, http_server))

    if not args.http_only:
        socks5_server = SOCKS5ProxyServer(
            rotator=rotator, host="0.0.0.0", port=args.socks5_port,
            username=args.username, password=args.password,
        )
        servers.append(("SOCKS5", args.socks5_port, socks5_server))

    for name, port, server in servers:
        await server.start()
        print(f"  [{name}]  listening on 0.0.0.0:{port}")

    print(f"\n  Pool: {args.pool_api} → /get?pool={args.pool_name}&min_score={args.min_score}")
    print(f"  Failover: max {args.max_retries} retries, timeout {args.connect_timeout}s")
    if args.username:
        print(f"  Auth: {args.username}:{args.password}")
        print(f"\n  FORMAT:  host:port:user:pass")
        creds = f"{args.username}:{args.password}@" if args.username else ""
        if not args.socks5_only:
            print(f"    http://{creds}localhost:{args.http_port}")
            print(f"    curl -x http://{args.username}:{args.password}@localhost:{args.http_port} http://api.ipify.org")
        if not args.http_only:
            print(f"    socks5://{creds}localhost:{args.socks5_port}")
            print(f"    curl -x socks5://{args.username}:{args.password}@localhost:{args.socks5_port} http://api.ipify.org")
    else:
        print(f"\n  No auth — anyone can use. Add --username and --password to secure.")
        print(f"\n  USE IT:")
        steps = []
        if not args.socks5_only:
            steps.append(f'    curl -x http://localhost:{args.http_port} http://api.ipify.org')
        if not args.http_only:
            steps.append(f'    curl -x socks5://localhost:{args.socks5_port} http://api.ipify.org')
        for s in steps:
            print(s)
    print()

    # --- Wait for shutdown ---
    stop_event = asyncio.Event()

    def _shutdown(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        stop_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    await stop_event.wait()

    # Cleanup
    for _, _, server in servers:
        await server.stop()
    await pool.stop()
    logger.info("Gateway stopped.")


if __name__ == "__main__":
    asyncio.run(main())
