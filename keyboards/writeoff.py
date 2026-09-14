from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from keyboards.callbacks import WriteoffCB


def _nav_row(step: str, *, show_back: bool) -> list[InlineKeyboardButton]:
    buttons: list[InlineKeyboardButton] = []
    if show_back:
        buttons.append(
            InlineKeyboardButton(
                text="« Назад",
                callback_data=WriteoffCB(action="back", step=step).pack(),
            )
        )
    buttons.append(
        InlineKeyboardButton(
            text="Отмена",
            callback_data=WriteoffCB(action="cancel").pack(),
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
                callback_data=WriteoffCB(
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
            callback_data=WriteoffCB(action="pick", step="qty", item_id=number).pack(),
        )
    builder.adjust(5)
    builder.row(*_nav_row("qty", show_back=True))
    return builder.as_markup()


def confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Списать",
            callback_data=WriteoffCB(action="save", step="confirm").pack(),
        )
    )
    builder.row(*_nav_row("confirm", show_back=True))
    return builder.as_markup()
