import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from config import settings
from db.engine import async_session_maker
from db.models import AppSetting

logger = logging.getLogger(__name__)

NOTICE_KEY = "notice_reservations"
NOTICE_TEXT = (
    "В продаже появилась бронь.\n"
    "\n"
    "Отложить клюшку: Продажа → как обычно до конца → вместо «Записать» нажми Забронировать. "
    "В наличии её не будет, в кассу ничего не попадёт.\n"
    "\n"
    "Забрать бронь: Продажа → Брони → нужная строка.\n"
    "\n"
    "- Записать — ещё раз увидишь сумму, потом чек и касса.\n"
    "- Отменить бронь — клюшка снова в наличии, без продажи.\n"
    "\n"
    "Ивач, я верю, что ты осилишь 💪🏻"
)


async def maybe_send_reservation_notice(bot: Bot) -> None:
    if not settings.admin_ids:
        return
    async with async_session_maker() as session:
        existing = await session.get(AppSetting, NOTICE_KEY)
        if existing is not None:
            return
        for admin_id in settings.admin_ids:
            try:
                await bot.send_message(admin_id, NOTICE_TEXT)
            except TelegramAPIError as exc:
                logger.warning("Не отправил уведомление админу %s: %s", admin_id, exc)
        session.add(AppSetting(key=NOTICE_KEY, value="1"))
        await session.commit()
