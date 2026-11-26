"""Flask WSGI adapter for the aiogram 3 community bot.

PythonAnywhere imports ``application`` from its WSGI file. A dedicated asyncio
thread keeps the aiogram/aiohttp objects on one event loop across WSGI calls.
"""

import asyncio
import hmac
import logging
import os
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Coroutine, TypeVar

from dotenv import load_dotenv

# Read local secrets before importing config.py (which reads BOT_TOKEN).
load_dotenv(Path(__file__).with_name(".env"), override=False)

from aiogram import Bot, Dispatcher
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

T = TypeVar("T")
_loop = asyncio.new_event_loop()
_bot: Bot | None = None
_dp: Dispatcher | None = None
_initialized = threading.Event()
_startup_error: BaseException | None = None


def _loop_worker() -> None:
    asyncio.set_event_loop(_loop)
    _loop.run_forever()


_thread = threading.Thread(target=_loop_worker, name="aiogram-event-loop", daemon=True)
_thread.start()


async def _initialize() -> None:
    global _bot, _dp
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        raise RuntimeError("Set BOT_TOKEN in the local .env or PythonAnywhere environment.")

    # Each helper opens and closes its own short-lived SQLite connection.
    await init_db()
    await seed_channels([(key, value) for key, value in LINKS.items() if value])
    await seed_settings({
        "welcome_ar": TEXTS["ar"]["welcome"],
        "welcome_en": TEXTS["en"]["welcome"],
    })

    session = AiohttpSession(proxy=PROXY_URL or None)
    _bot = Bot(
        BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    _dp = Dispatcher(storage=MemoryStorage())
    _dp.include_router(router)
    _dp.include_router(admin_router)


def _start_once() -> None:
    global _startup_error
    try:
        asyncio.run_coroutine_threadsafe(_initialize(), _loop).result(timeout=60)
    except BaseException as exc:
        _startup_error = exc
        logger.exception("Failed to initialize Telegram bot or database")
    finally:
        _initialized.set()


_startup_thread = threading.Thread(target=_start_once, name="bot-initialization", daemon=True)
_startup_thread.start()


def _run(coro: Coroutine[Any, Any, T]) -> T:
    if not _initialized.wait(timeout=60):
        coro.close()
        raise TimeoutError("Bot initialization did not finish in time")
    if _startup_error is not None:
        coro.close()
        raise RuntimeError("Bot initialization failed") from _startup_error
    future: Future[T] = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=60)


async def _process_update(payload: dict[str, Any]) -> None:
    assert _bot is not None and _dp is not None
    update = Update.model_validate(payload, context={"bot": _bot})
    await _dp.feed_update(_bot, update)


async def _register_webhook() -> bool:
    assert _bot is not None
    await _bot.set_my_commands([
        BotCommand(command="start", description="Start / الرئيسية"),
        BotCommand(command="language", description="Change language / تغيير اللغة"),
    ])
    await _bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    return await _bot.set_webhook(
        url=WEBHOOK_URL,
        drop_pending_updates=True,
        secret_token=WEBHOOK_SECRET or None,
    )


app = Flask(__name__)
application = app


@app.get("/")
def health_check():
    if _initialized.is_set() and _startup_error is not None:
        return jsonify(status="error", detail="Bot initialization failed"), 503
    return jsonify(status="ok", initialized=_initialized.is_set()), 200


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
        _run(_process_update(payload))
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
        _run(_register_webhook())
    except Exception:
        logger.exception("Telegram setWebhook failed")
        return jsonify(error="Telegram rejected setWebhook"), 502
    return jsonify(status="ok", webhook_url=WEBHOOK_URL, pending_updates_dropped=True)
