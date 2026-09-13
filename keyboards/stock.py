from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.models import City
from keyboards.callbacks import StockCB


def cities_keyboard(rows: Sequence[tuple[City, int]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for city, qty in rows:
        builder.row(
            InlineKeyboardButton(
                text=f"{city.name} — {qty} шт",
                callback_data=StockCB(action="city", item_id=city.id).pack(),
            )
        )
    return builder.as_markup()


def city_stock_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="« Города",
            callback_data=StockCB(action="cities").pack(),
        )
    )
    return builder.as_markup()
