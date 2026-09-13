from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import settings


class AdminOnlyMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        user_id = user.id if user is not None else 0
        if not settings.is_admin(user_id):
            if isinstance(event, Message):
                await event.answer("Доступ только для администратора.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Доступ только для администратора.", show_alert=True)
            return None
        return await handler(event, data)
