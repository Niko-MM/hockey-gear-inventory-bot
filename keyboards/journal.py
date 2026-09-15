from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from keyboards.callbacks import JournalCB, NavCB
from repositories.journal import JournalEntry


def journal_list_keyboard(
    entries: Sequence[JournalEntry],
    *,
    period: bool = False,
    page: int = 0,
    pages: int = 1,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for entry in entries:
        builder.row(
            InlineKeyboardButton(
                text=entry.button[:64],
                callback_data=JournalCB(
                    action="open",
                    kind=entry.kind,
                    item_id=entry.item_id,
                ).pack(),
            )
        )
    if period and pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    text="«",
                    callback_data=JournalCB(action="page", item_id=page - 1).pack(),
                )
            )
        if page + 1 < pages:
            nav.append(
                InlineKeyboardButton(
                    text="»",
                    callback_data=JournalCB(action="page", item_id=page + 1).pack(),
                )
            )
        if nav:
            builder.row(*nav)
    if period:
        builder.row(
            InlineKeyboardButton(
                text="Другие даты",
                callback_data=JournalCB(action="range").pack(),
            )
        )
        builder.row(
            InlineKeyboardButton(text="« Журнал", callback_data=JournalCB(action="list").pack())
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text="За период",
                callback_data=JournalCB(action="range").pack(),
            )
        )
        builder.row(
            InlineKeyboardButton(text="« Сервис", callback_data=NavCB(to="service").pack())
        )
    return builder.as_markup()


def journal_nav_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Отмена", callback_data=JournalCB(action="list").pack())
    )
    return builder.as_markup()


def journal_end_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Сегодня",
            callback_data=JournalCB(action="today").pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(text="Отмена", callback_data=JournalCB(action="list").pack())
    )
    return builder.as_markup()


def journal_card_keyboard(entry: JournalEntry) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if entry.can_undo:
        builder.row(
            InlineKeyboardButton(
                text="Отменить",
                callback_data=JournalCB(
                    action="ask",
                    kind=entry.kind,
                    item_id=entry.item_id,
                ).pack(),
            )
        )
    builder.row(
        InlineKeyboardButton(text="« Журнал", callback_data=JournalCB(action="back").pack())
    )
    return builder.as_markup()


def journal_confirm_keyboard(kind: str, item_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Отменить",
            callback_data=JournalCB(action="undo", kind=kind, item_id=item_id).pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="« Назад",
            callback_data=JournalCB(action="open", kind=kind, item_id=item_id).pack(),
        )
    )
    return builder.as_markup()
