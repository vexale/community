"""Start the aiogram 3 community support bot."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, MenuButtonCommands
from aiogram.fsm.storage.memory import MemoryStorage

from admin_handlers import router as admin_router
from config import BOT_TOKEN, LINKS, PROXY_URL
from database import init_db, seed_channels, seed_settings
from handlers import router
from texts import TEXTS


async def main() -> None:
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        raise RuntimeError("Set BOT_TOKEN in your .env file before starting the bot.")

    logging.basicConfig(level=logging.INFO)
    await init_db()
    await seed_channels([(key, value) for key, value in LINKS.items() if value])
    await seed_settings({
        "welcome_ar": TEXTS["ar"]["welcome"],
        "welcome_en": TEXTS["en"]["welcome"],
    })
    session = AiohttpSession(proxy=PROXY_URL or None)
    bot = Bot(
        BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    dp.include_router(admin_router)
    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Start / الرئيسية"),
                BotCommand(command="language", description="Change language / تغيير اللغة"),
            ]
        )
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
