import asyncio
import os
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

# Ensure src/ is on sys.path when run directly with `uv run src/main.py`
sys.path.insert(0, os.path.dirname(__file__))

from proxy_pool.api.routes import router
from proxy_pool.core.scheduler import fetch_job, scheduler, setup_scheduler
from proxy_pool.core.storage import storage
from proxy_pool.utils.config import settings
from proxy_pool.utils.logger import logger

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("myproxypool starting up...")
    await storage.connect()
    setup_scheduler()
    scheduler.start()

    # Trigger an immediate fetch on first start
    asyncio.create_task(fetch_job())

    yield

    # Shutdown
    logger.info("myproxypool shutting down...")
    scheduler.shutdown(wait=False)
    await storage.close()

app = FastAPI(
    title="myproxypool",
    description="Integrated proxy pool — 11 sources, 3-state validation, scoring system",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)

@app.get("/")
async def root():
    return {
        "name": "myproxypool",
        "version": "0.1.0",
        "endpoints": ["/get", "/all", "/stats", "/delete"],
    }

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )
