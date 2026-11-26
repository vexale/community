"""Flask WSGI adapter for the aiogram 3 community bot.

Each WSGI request gets its own asyncio loop, Bot, Dispatcher, and aiohttp
session. The process-wide MemoryStorage preserves FSM state between requests.
"""

import asyncio
import copy
import hmac
import logging
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from dotenv import load_dotenv

# Read local secrets before importing config.py (which reads BOT_TOKEN).
load_dotenv(Path(__file__).with_name(".env"), override=False)

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, MenuButtonCommands, Update
from flask import Flask, abort, jsonify, request

from admin_handlers import router as admin_router
from config import BOT_TOKEN, LINKS, PROXY_URL
from database import init_db, seed_channels, seed_settings
from handlers import router
from texts import TEXTS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WEBHOOK_URL = os.getenv(
    "WEBHOOK_URL", "https://vexale.pythonanywhere.com/webhook"
).strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
SET_WEBHOOK_SECRET = os.getenv("SET_WEBHOOK_SECRET", "").strip()

_is_initialized = False
# MemoryStorage is loop-independent and keeps the multi-step report wizard state
# across the fresh Dispatcher instances required for each asyncio.run call.
_fsm_storage = MemoryStorage()


async def _ensure_initialized() -> None:
    """Initialize the schema and default rows once per WSGI process."""
    global _is_initialized
    if _is_initialized:
        return
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        raise RuntimeError("Set BOT_TOKEN in the local .env or PythonAnywhere environment.")

    await init_db()
    await seed_channels([(key, value) for key, value in LINKS.items() if value])
    await seed_settings({
        "welcome_ar": TEXTS["ar"]["welcome"],
        "welcome_en": TEXTS["en"]["welcome"],
    })
    _is_initialized = True


def _copy_router(source: Router) -> Router:
    """Make a fresh router tree so it can be attached to each new Dispatcher."""
    return copy.deepcopy(source)


async def _with_bot(
    operation: Callable[..., Awaitable[Any]], *args: Any
) -> Any:
    """Run a bot operation with resources bound to this asyncio event loop."""
    await _ensure_initialized()
    session = AiohttpSession(proxy=PROXY_URL or None)
    try:
        bot = Bot(
            BOT_TOKEN,
            session=session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        dp = Dispatcher(storage=_fsm_storage)
        dp.include_router(_copy_router(router))
        dp.include_router(_copy_router(admin_router))
        return await operation(bot, dp, *args)
    finally:
        await session.close()


async def _feed_update(bot: Bot, dp: Dispatcher, payload: dict[str, Any]) -> None:
    update = Update.model_validate(payload, context={"bot": bot})
    await dp.feed_update(bot, update)


async def _register_webhook(bot: Bot, _dp: Dispatcher) -> bool:
    await bot.set_my_commands([
        BotCommand(command="start", description="Start / الرئيسية"),
        BotCommand(command="language", description="Change language / تغيير اللغة"),
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    return await bot.set_webhook(
        url=WEBHOOK_URL,
        drop_pending_updates=True,
        secret_token=WEBHOOK_SECRET or None,
    )


app = Flask(__name__)
application = app


@app.get("/")
def health_check():
    return jsonify(status="ok"), 200


@app.post("/webhook")
def telegram_webhook():
    if WEBHOOK_SECRET:
        supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(supplied, WEBHOOK_SECRET):
            abort(403)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Expected a JSON Telegram Update"), 400
    try:
        asyncio.run(_with_bot(_feed_update, payload))
    except Exception:
        logger.exception("Failed to process Telegram update")
        return jsonify(error="Update processing failed"), 500
    return "OK", 200


@app.post("/set_webhook")
def set_webhook():
    if not SET_WEBHOOK_SECRET:
        return jsonify(error="SET_WEBHOOK_SECRET is not configured"), 503
    supplied = request.headers.get("X-Setup-Secret", "")
    if not hmac.compare_digest(supplied, SET_WEBHOOK_SECRET):
        abort(403)
    if not WEBHOOK_URL.startswith("https://"):
        return jsonify(error="WEBHOOK_URL must use HTTPS"), 500

    try:
        asyncio.run(_with_bot(_register_webhook))
    except Exception:
        logger.exception("Telegram setWebhook failed")
        return jsonify(error="Telegram rejected setWebhook"), 502
    return jsonify(status="ok", webhook_url=WEBHOOK_URL, pending_updates_dropped=True)
