"""Minimal aiohttp health endpoint for hosts that expect a web service."""

import asyncio
import os

from aiohttp import web


async def _health(_request: web.Request) -> web.Response:
    return web.Response(text="Community support bot is running.", content_type="text/plain")


async def start_keep_alive(host: str | None = None, port: int | None = None) -> web.AppRunner:
    """Start the lightweight server and return its runner for cleanup."""
    app = web.Application()
    app.router.add_get("/", _health)
    app.router.add_get("/health", _health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(
        runner,
        host or os.getenv("HOST", "0.0.0.0"),
        port or int(os.getenv("PORT", "8080")),
    )
    await site.start()
    return runner


async def run_keep_alive() -> None:
    """Standalone mode for hosting environments that launch this file directly."""
    runner = await start_keep_alive()
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(run_keep_alive())
