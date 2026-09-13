from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.models import City
from keyboards.callbacks import StockCB

AXIS_LABELS = {
    "flex": "Флекс",
    "grip": "Хват",
    "curve": "Загиб",
}


def cities_keyboard(rows: Sequence[tuple[City, int]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for city, qty in rows:
        builder.row(
            InlineKeyboardButton(
                text=f"{city.name} — {qty} шт",
                callback_data=StockCB(action="menu", city_id=city.id).pack(),
            )
        )
    return builder.as_markup()


def view_menu_keyboard(city_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Как обычно",
            callback_data=StockCB(action="view", city_id=city_id, axis="default").pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="Флекс",
            callback_data=StockCB(action="values", city_id=city_id, axis="flex").pack(),
        ),
        InlineKeyboardButton(
            text="Хват",
            callback_data=StockCB(action="values", city_id=city_id, axis="grip").pack(),
        ),
        InlineKeyboardButton(
            text="Загиб",
            callback_data=StockCB(action="values", city_id=city_id, axis="curve").pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="« Города",
            callback_data=StockCB(action="cities").pack(),
        )
    )
    return builder.as_markup()


def values_keyboard(
    city_id: int,
    axis: str,
    items: Sequence[tuple[int, str, int]],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item_id, title, qty in items:
        builder.row(
            InlineKeyboardButton(
                text=f"{title} — {qty} шт",
                callback_data=StockCB(
                    action="view",
                    city_id=city_id,
                    item_id=item_id,
                    axis=axis,
                ).pack(),
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="« Как смотреть",
            callback_data=StockCB(action="menu", city_id=city_id).pack(),
        )
    )
    return builder.as_markup()


def back_keyboard(city_id: int, *, axis: str = "") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if axis in AXIS_LABELS:
        builder.row(
            InlineKeyboardButton(
                text=f"« {AXIS_LABELS[axis]}",
                callback_data=StockCB(action="values", city_id=city_id, axis=axis).pack(),
            )
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text="« Как смотреть",
                callback_data=StockCB(action="menu", city_id=city_id).pack(),
            )
        )
    return builder.as_markup()
