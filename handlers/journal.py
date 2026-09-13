# pyright: reportUnusedCallResult=false
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from keyboards.callbacks import JournalCB, NavCB
from keyboards.journal import journal_card_keyboard, journal_confirm_keyboard, journal_list_keyboard
from repositories import journal as journal_repo
from repositories.journal import CannotUndoError

router = Router()


def _callback_message(callback: CallbackQuery) -> Message | None:
    message = callback.message
    return message if isinstance(message, Message) else None


async def _show_list(
    session: AsyncSession,
    *,
    callback: CallbackQuery | None = None,
    notice: str = "",
) -> None:
    entries = await journal_repo.list_entries(session)
    title = "Журнал пуст." if not entries else "Журнал"
    text = f"{notice}\n\n{title}" if notice else title
    markup = journal_list_keyboard(entries)
    target = _callback_message(callback) if callback else None
    if target:
        await target.edit_text(text, reply_markup=markup)


@router.callback_query(NavCB.filter(F.to == "edits"))
async def open_journal(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    await callback.answer()
    await _show_list(session, callback=callback)


@router.callback_query(JournalCB.filter(F.action == "list"))
async def list_journal(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await _show_list(session, callback=callback)


@router.callback_query(JournalCB.filter(F.action == "open"))
async def open_entry(
    callback: CallbackQuery,
    callback_data: JournalCB,
    session: AsyncSession,
) -> None:
    entry = await journal_repo.get_entry(session, callback_data.kind, callback_data.item_id)
    if entry is None:
        await callback.answer("Запись уже удалена.", show_alert=True)
        await _show_list(session, callback=callback)
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
) -> None:
    entry = await journal_repo.get_entry(session, callback_data.kind, callback_data.item_id)
    if entry is None:
        await callback.answer("Запись уже удалена.", show_alert=True)
        await _show_list(session, callback=callback)
        return
    if not entry.can_undo:
        await callback.answer(entry.block_reason or "Это уже нельзя удалить.", show_alert=True)
        return
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.edit_text(
            f"{entry.title}\n\n{entry.body}\n\nУдалить?",
            reply_markup=journal_confirm_keyboard(entry.kind, entry.item_id),
        )


@router.callback_query(JournalCB.filter(F.action == "undo"))
async def undo_entry(
    callback: CallbackQuery,
    callback_data: JournalCB,
    session: AsyncSession,
) -> None:
    try:
        await journal_repo.undo_entry(session, callback_data.kind, callback_data.item_id)
    except CannotUndoError as exc:
        await callback.answer(exc.reason, show_alert=True)
        await _show_list(session, callback=callback)
        return
    await callback.answer()
    await _show_list(session, callback=callback, notice="✅ Удалил")
