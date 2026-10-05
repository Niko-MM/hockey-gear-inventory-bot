from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from keyboards.callbacks import SaleCB


def _nav_row(step: str, *, show_back: bool) -> list[InlineKeyboardButton]:
    buttons: list[InlineKeyboardButton] = []
    if show_back:
        buttons.append(
            InlineKeyboardButton(
                text="« Назад",
                callback_data=SaleCB(action="back", step=step).pack(),
            )
        )
    buttons.append(
        InlineKeyboardButton(
            text="Отмена",
            callback_data=SaleCB(action="cancel").pack(),
        )
    )
    return buttons


def choice_keyboard(
    items: Sequence[tuple[int, int, str]],
    step: str,
    *,
    show_back: bool,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item_id, extra_id, title in items:
        builder.row(
            InlineKeyboardButton(
                text=title,
                callback_data=SaleCB(
                    action="pick",
                    step=step,
                    item_id=item_id,
                    extra_id=extra_id,
                ).pack(),
            )
        )
    builder.row(*_nav_row(step, show_back=show_back))
    return builder.as_markup()


def qty_keyboard(remaining: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    shown = min(remaining, 10)
    for number in range(1, shown + 1):
        builder.button(
            text=str(number),
            callback_data=SaleCB(action="pick", step="qty", item_id=number).pack(),
        )
    builder.adjust(5)
    builder.row(*_nav_row("qty", show_back=True))
    return builder.as_markup()


def nav_keyboard(step: str, *, show_back: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(*_nav_row(step, show_back=show_back))
    return builder.as_markup()


def city_keyboard(
    items: Sequence[tuple[int, int, str]],
    hold_qty: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if hold_qty:
        builder.row(
            InlineKeyboardButton(
                text=f"Брони ({hold_qty})",
                callback_data=SaleCB(action="holds").pack(),
            )
        )
    for item_id, extra_id, title in items:
        builder.row(
            InlineKeyboardButton(
                text=title,
                callback_data=SaleCB(
                    action="pick",
                    step="city",
                    item_id=item_id,
                    extra_id=extra_id,
                ).pack(),
            )
        )
    builder.row(*_nav_row("city", show_back=False))
    return builder.as_markup()


def holds_keyboard(items: Sequence[tuple[int, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for hold_id, title in items:
        builder.row(
            InlineKeyboardButton(
                text=title[:64],
                callback_data=SaleCB(action="hold", item_id=hold_id).pack(),
            )
        )
    builder.row(*_nav_row("holds", show_back=True))
    return builder.as_markup()


def hold_card_keyboard(hold_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Записать",
            callback_data=SaleCB(action="hold_save", item_id=hold_id).pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="Отменить бронь",
            callback_data=SaleCB(action="hold_cancel", item_id=hold_id).pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="« Назад",
            callback_data=SaleCB(action="holds").pack(),
        ),
        InlineKeyboardButton(
            text="Отмена",
            callback_data=SaleCB(action="cancel").pack(),
        ),
    )
    return builder.as_markup()


def confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Записать",
            callback_data=SaleCB(action="save", step="confirm").pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="Забронировать",
            callback_data=SaleCB(action="reserve", step="confirm").pack(),
        )
    )
    builder.row(*_nav_row("confirm", show_back=True))
    return builder.as_markup()
