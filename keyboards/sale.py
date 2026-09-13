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


def nav_keyboard(step: str, *, show_back: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(*_nav_row(step, show_back=show_back))
    return builder.as_markup()


def confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Записать",
            callback_data=SaleCB(action="save", step="confirm").pack(),
        )
    )
    builder.row(*_nav_row("confirm", show_back=True))
    return builder.as_markup()
