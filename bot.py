import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage

from config import settings
from db import init_db
from handlers.cash import router as cash_router
from handlers.common import router as common_router
from handlers.income import router as income_router
from handlers.management import router as management_router
from handlers.menu import router as menu_router
from handlers.sale import router as sale_router
from middlewares.admin import AdminOnlyMiddleware
from middlewares.db import DbSessionMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    await init_db()

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(AdminOnlyMiddleware())
    dp.update.middleware(DbSessionMiddleware())
    dp.include_router(common_router)
    dp.include_router(management_router)
    dp.include_router(cash_router)
    dp.include_router(income_router)
    dp.include_router(sale_router)
    dp.include_router(menu_router)

    logger.info("Бот запущен (polling)")
    try:
        await dp.start_polling(bot)
    except TelegramNetworkError:
        logger.error(
            "Нет доступа к api.telegram.org. "
            "Проверь интернет или VPN (Telegram часто недоступен без него)."
        )
    except TelegramUnauthorizedError:
        logger.error("Неверный BOT_TOKEN. Проверь .env и токен у BotFather.")


if __name__ == "__main__":
    asyncio.run(main())
