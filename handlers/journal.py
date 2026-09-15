# pyright: reportUnusedCallResult=false
from datetime import date

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from keyboards.callbacks import JournalCB, NavCB
from keyboards.journal import (
    journal_card_keyboard,
    journal_confirm_keyboard,
    journal_end_keyboard,
    journal_list_keyboard,
    journal_nav_keyboard,
)
from keyboards.menu import BTN_INCOME, BTN_SALE, BTN_SERVICE, BTN_STOCK
from repositories import journal as journal_repo
from repositories.journal import JOURNAL_LIMIT, CannotUndoError
from states.journal import JournalPeriod
from utils.dates import format_input_date, format_range, parse_date, today

router = Router()

MENU_TEXTS = {BTN_SALE, BTN_INCOME, BTN_STOCK, BTN_SERVICE}


def _callback_message(callback: CallbackQuery) -> Message | None:
    message = callback.message
    return message if isinstance(message, Message) else None


async def _remember_prompt(state: FSMContext, message: Message) -> None:
    await state.update_data(
        prompt_chat_id=message.chat.id,
        prompt_message_id=message.message_id,
    )


async def _delete_prompt(bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    chat_id = data.get("prompt_chat_id")
    message_id = data.get("prompt_message_id")
    if not isinstance(chat_id, int) or not isinstance(message_id, int):
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramBadRequest:
        pass


def _period_from_data(data: dict) -> tuple[date, date] | None:
    raw_start = data.get("journal_start")
    raw_end = data.get("journal_end")
    if not isinstance(raw_start, str) or not isinstance(raw_end, str):
        return None
    return date.fromisoformat(raw_start), date.fromisoformat(raw_end)


async def _show_recent(
    session: AsyncSession,
    state: FSMContext,
    *,
    callback: CallbackQuery | None = None,
    notice: str = "",
) -> None:
    await state.update_data(journal_start=None, journal_end=None, journal_page=0)
    entries = await journal_repo.list_entries(session)
    title = "Журнал пуст." if not entries else "Журнал"
    text = f"{notice}\n\n{title}" if notice else title
    markup = journal_list_keyboard(entries)
    target = _callback_message(callback) if callback else None
    if target:
        await target.edit_text(text, reply_markup=markup)


async def _show_period(
    session: AsyncSession,
    state: FSMContext,
    start: date,
    end: date,
    *,
    page: int = 0,
    callback: CallbackQuery | None = None,
    notice: str = "",
) -> None:
    entries, total = await journal_repo.list_period(session, start, end, page=page)
    pages = max(1, (total + JOURNAL_LIMIT - 1) // JOURNAL_LIMIT)
    if total:
        page = min(max(page, 0), pages - 1)
    await state.update_data(
        journal_start=start.isoformat(),
        journal_end=end.isoformat(),
        journal_page=page,
    )
    header = f"Журнал · {format_range(start, end)}"
    if total > JOURNAL_LIMIT:
        header = f"{header} · {page + 1}/{pages}"
    if total == 0:
        body = f"{header}\n\nЗа эти дни записей нет."
    else:
        body = header
    text = f"{notice}\n\n{body}" if notice else body
    markup = journal_list_keyboard(entries, period=True, page=page, pages=pages)
    target = _callback_message(callback) if callback else None
    if target:
        await target.edit_text(text, reply_markup=markup)


async def _show_current(
    session: AsyncSession,
    state: FSMContext,
    *,
    callback: CallbackQuery | None = None,
    notice: str = "",
) -> None:
    data = await state.get_data()
    period = _period_from_data(data)
    if period is None:
        await _show_recent(session, state, callback=callback, notice=notice)
        return
    start, end = period
    page = data.get("journal_page")
    page_n = page if isinstance(page, int) else 0
    await _show_period(session, state, start, end, page=page_n, callback=callback, notice=notice)


@router.callback_query(NavCB.filter(F.to == "edits"))
async def open_journal(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    await callback.answer()
    await _show_recent(session, state, callback=callback)


@router.callback_query(JournalCB.filter(F.action == "list"))
async def list_journal(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.set_state(None)
    await callback.answer()
    await _show_recent(session, state, callback=callback)


@router.callback_query(JournalCB.filter(F.action == "back"))
async def back_journal(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await callback.answer()
    await _show_current(session, state, callback=callback)


@router.callback_query(JournalCB.filter(F.action == "page"))
async def page_journal(
    callback: CallbackQuery,
    callback_data: JournalCB,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    period = _period_from_data(data)
    if period is None:
        await callback.answer()
        await _show_recent(session, state, callback=callback)
        return
    await callback.answer()
    start, end = period
    await _show_period(session, state, start, end, page=callback_data.item_id, callback=callback)


@router.callback_query(JournalCB.filter(F.action == "range"))
async def start_period(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(JournalPeriod.start)
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.edit_text(
            f"С какого числа? Сегодня {format_input_date(today())}",
            reply_markup=journal_nav_keyboard(),
        )
        await _remember_prompt(state, message)


@router.message(JournalPeriod.start, F.text, ~F.text.in_(MENU_TEXTS))
async def save_period_start(message: Message, state: FSMContext) -> None:
    start = parse_date(message.text or "")
    if start is None:
        await message.answer(f"Напиши дату так: {format_input_date(today())}")
        return
    await state.update_data(journal_start=start.isoformat())
    await state.set_state(JournalPeriod.end)
    await _delete_prompt(message.bot, state)
    sent = await message.answer(
        f"По какое число? Сегодня {format_input_date(today())}",
        reply_markup=journal_end_keyboard(),
    )
    await _remember_prompt(state, sent)


@router.message(JournalPeriod.end, F.text, ~F.text.in_(MENU_TEXTS))
async def save_period_end(message: Message, state: FSMContext, session: AsyncSession) -> None:
    end = parse_date(message.text or "")
    if end is None:
        await message.answer(f"Напиши дату так: {format_input_date(today())}")
        return
    data = await state.get_data()
    raw_start = data.get("journal_start")
    if not isinstance(raw_start, str):
        await state.clear()
        await message.answer("Начни журнал заново.")
        return
    start = date.fromisoformat(raw_start)
    if start > end:
        await message.answer("Начало позже конца. Напиши ещё раз.")
        return
    await _delete_prompt(message.bot, state)
    await state.set_state(None)
    await state.update_data(
        journal_start=start.isoformat(),
        journal_end=end.isoformat(),
        journal_page=0,
    )
    entries, total = await journal_repo.list_period(session, start, end, page=0)
    pages = max(1, (total + JOURNAL_LIMIT - 1) // JOURNAL_LIMIT)
    header = f"Журнал · {format_range(start, end)}"
    if total > JOURNAL_LIMIT:
        header = f"{header} · 1/{pages}"
    body = f"{header}\n\nЗа эти дни записей нет." if total == 0 else header
    await message.answer(
        body,
        reply_markup=journal_list_keyboard(entries, period=True, page=0, pages=pages),
    )


@router.callback_query(
    JournalPeriod.end,
    JournalCB.filter(F.action == "today"),
)
async def period_today(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    raw_start = data.get("journal_start")
    if not isinstance(raw_start, str):
        await callback.answer("Начни журнал заново.", show_alert=True)
        await state.clear()
        return
    start = date.fromisoformat(raw_start)
    end = today()
    if start > end:
        await callback.answer("Начало позже сегодня. Напиши дату конца.", show_alert=True)
        return
    await state.set_state(None)
    await callback.answer()
    await _show_period(session, state, start, end, page=0, callback=callback)


@router.callback_query(JournalCB.filter(F.action == "open"))
async def open_entry(
    callback: CallbackQuery,
    callback_data: JournalCB,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    entry = await journal_repo.get_entry(session, callback_data.kind, callback_data.item_id)
    if entry is None:
        await callback.answer("Этой записи уже нет.", show_alert=True)
        await _show_current(session, state, callback=callback)
        return
    await callback.answer()
    message = _callback_message(callback)
    if not message:
        return
    extra = "" if entry.can_undo else f"\n\n{entry.block_reason}"
    await message.edit_text(
        f"{entry.title}\n\n{entry.body}{extra}",
        reply_markup=journal_card_keyboard(entry),
    )


@router.callback_query(JournalCB.filter(F.action == "ask"))
async def ask_undo(
    callback: CallbackQuery,
    callback_data: JournalCB,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    entry = await journal_repo.get_entry(session, callback_data.kind, callback_data.item_id)
    if entry is None:
        await callback.answer("Этой записи уже нет.", show_alert=True)
        await _show_current(session, state, callback=callback)
        return
    if not entry.can_undo:
        await callback.answer(entry.block_reason or "Это уже нельзя отменить.", show_alert=True)
        return
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.edit_text(
            f"{entry.title}\n\n{entry.body}\n\nОтменить?",
            reply_markup=journal_confirm_keyboard(entry.kind, entry.item_id),
        )


@router.callback_query(JournalCB.filter(F.action == "undo"))
async def undo_entry(
    callback: CallbackQuery,
    callback_data: JournalCB,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    try:
        await journal_repo.undo_entry(session, callback_data.kind, callback_data.item_id)
    except CannotUndoError as exc:
        await callback.answer(exc.reason, show_alert=True)
        await _show_current(session, state, callback=callback)
        return
    await callback.answer()
    await _show_current(session, state, callback=callback, notice="✅ Отменил")
