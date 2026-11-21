"""Start the aiogram 3 community support bot."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, MenuButtonCommands
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from database import init_db
from handlers import router
from keep_alive import start_keep_alive


async def main() -> None:
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        raise RuntimeError("Set BOT_TOKEN in your .env file before starting the bot.")

    logging.basicConfig(level=logging.INFO)
    await init_db()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    runner = await start_keep_alive()
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
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
