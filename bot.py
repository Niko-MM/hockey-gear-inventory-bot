import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message

from config import settings
from db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def cmd_start(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    if not settings.is_admin(user_id):
        await message.answer("Доступ только для администратора.")
        return

    await message.answer(
        "Привет. Это бот учёта товара и продаж.\n"
        "Скелет запущен: дальше подключим каталог, партии и отчёты."
    )


async def main() -> None:
    await init_db()

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    dp.message.register(cmd_start, CommandStart())

    logger.info("Бот запущен (polling)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
