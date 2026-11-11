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

SELLER_NOTICE_KEY = "notice_seller_hide"
SELLER_NOTICE_TEXT = (
    "🏒 Клюшки мутятся, бот крутится. Возможно, я что-то напутал 👀\n"
    "🛠 Что обновил:\n"
    "• Пофиксил баг с удалением кассира.\n"
    "• Новые правила удаления: баланс должен быть 0, а на кассире не должно висеть забронированных клюшек.\n"
    "• Из списков он пропадёт. В журнале и отчётах имя останется с его историей. Чтобы вернуть, добавь то же имя ещё раз."
)


async def _send_once(bot: Bot, key: str, text: str) -> None:
    if not settings.admin_ids:
        return
    async with async_session_maker() as session:
        existing = await session.get(AppSetting, key)
        if existing is not None:
            return
        delivered = False
        for admin_id in settings.admin_ids:
            try:
                await bot.send_message(admin_id, text)
                delivered = True
            except TelegramAPIError as exc:
                logger.warning("Не отправил уведомление админу %s: %s", admin_id, exc)
        if not delivered:
            return
        session.add(AppSetting(key=key, value="1"))
        await session.commit()


async def maybe_send_reservation_notice(bot: Bot) -> None:
    await _send_once(bot, NOTICE_KEY, NOTICE_TEXT)


async def maybe_send_seller_notice(bot: Bot) -> None:
    await _send_once(bot, SELLER_NOTICE_KEY, SELLER_NOTICE_TEXT)
