from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.models import City
from keyboards.callbacks import StockCB


def back_to_cities_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="« Города",
            callback_data=StockCB(action="cities").pack(),
        )
    )
    return builder.as_markup()


def cities_keyboard(rows: Sequence[tuple[City, int]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for city, qty in rows:
        builder.row(
            InlineKeyboardButton(
                text=f"{city.name} — {qty} шт",
                callback_data=StockCB(action="grips", city_id=city.id).pack(),
            )
        )
    return builder.as_markup()


def grips_keyboard(city_id: int, items: Sequence[tuple[int, str, int]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for grip_id, title, qty in items:
        builder.row(
            InlineKeyboardButton(
                text=f"{title} — {qty} шт",
                callback_data=StockCB(action="flexes", city_id=city_id, grip_id=grip_id).pack(),
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="« Города",
            callback_data=StockCB(action="cities").pack(),
        )
    )
    return builder.as_markup()


def flexes_keyboard(
    city_id: int,
    grip_id: int,
    items: Sequence[tuple[int, str, int]],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for flex_id, title, qty in items:
        builder.row(
            InlineKeyboardButton(
                text=f"{title} — {qty} шт",
                callback_data=StockCB(
                    action="curves",
                    city_id=city_id,
                    grip_id=grip_id,
                    flex_id=flex_id,
                ).pack(),
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="« Хват",
            callback_data=StockCB(action="grips", city_id=city_id).pack(),
        )
    )
    return builder.as_markup()


def curves_keyboard(
    city_id: int,
    grip_id: int,
    flex_id: int,
    items: Sequence[tuple[int, str, int]],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for curve_id, title, qty in items:
        builder.row(
            InlineKeyboardButton(
                text=f"{title} — {qty} шт",
                callback_data=StockCB(
                    action="view",
                    city_id=city_id,
                    grip_id=grip_id,
                    flex_id=flex_id,
                    curve_id=curve_id,
                ).pack(),
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="« Флекс",
            callback_data=StockCB(action="flexes", city_id=city_id, grip_id=grip_id).pack(),
        )
    )
    return builder.as_markup()


def back_keyboard(city_id: int, *, grip_id: int = 0, flex_id: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if grip_id and flex_id:
        builder.row(
            InlineKeyboardButton(
                text="« Загиб",
                callback_data=StockCB(
                    action="curves",
                    city_id=city_id,
                    grip_id=grip_id,
                    flex_id=flex_id,
                ).pack(),
            )
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text="« Хват",
                callback_data=StockCB(action="grips", city_id=city_id).pack(),
            )
        )
    return builder.as_markup()
