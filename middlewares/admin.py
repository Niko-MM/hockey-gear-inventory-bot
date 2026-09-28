from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import settings
from keyboards.menu import BTN_STOCK


def _command_name(text: str) -> str:
    if not text.startswith("/"):
        return ""
    first = text.split()[0]
    return first[1:].split("@", 1)[0].lower()


def _is_public_allowed(event: TelegramObject) -> bool:
    if isinstance(event, Message):
        text = event.text or ""
        if _command_name(text) in {"start", "cancel"}:
            return True
        return text == BTN_STOCK
    if isinstance(event, CallbackQuery):
        data = event.data or ""
        return data.startswith("stk:")
    return False


class AdminOnlyMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        user_id = user.id if user is not None else 0
        if settings.is_admin(user_id) or _is_public_allowed(event):
            return await handler(event, data)
        if isinstance(event, Message):
            await event.answer("Доступна только кнопка «В наличии».")
        elif isinstance(event, CallbackQuery):
            await event.answer("Доступна только кнопка «В наличии».", show_alert=True)
        return None
