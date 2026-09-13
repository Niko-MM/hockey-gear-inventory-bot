from decimal import Decimal

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.models import Seller
from keyboards.callbacks import ManageCB, NavCB


def cash_menu(rows: list[tuple[Seller, Decimal]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if len(rows) >= 2:
        builder.button(
            text="Перевести",
            callback_data=ManageCB(section="cash", action="from").pack(),
        )
    builder.button(text="« Сервис", callback_data=NavCB(to="service").pack())
    builder.adjust(1)
    return builder.as_markup()


def pick_seller_keyboard(
    sellers: list[Seller],
    action: str,
    skip_id: int = 0,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for seller in sellers:
        if seller.id == skip_id:
            continue
        builder.row(
            InlineKeyboardButton(
                text=seller.name,
                callback_data=ManageCB(
                    section="cash",
                    action=action,
                    item_id=seller.id,
                ).pack(),
            )
        )
    builder.row(
        InlineKeyboardButton(text="« Кассы", callback_data=NavCB(to="accounting").pack())
    )
    return builder.as_markup()
