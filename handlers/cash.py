# pyright: reportUnusedCallResult=false
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from keyboards.callbacks import ManageCB, NavCB
from keyboards.cash import cash_menu, pick_seller_keyboard
from keyboards.menu import BTN_INCOME, BTN_SALE, BTN_SERVICE, BTN_STOCK
from repositories import sellers as sellers_repo
from repositories.catalog import InUseError
from repositories.sellers import InsufficientFundsError
from states.sellers import TransferCash

router = Router()

MENU_TEXTS = {BTN_SALE, BTN_INCOME, BTN_STOCK, BTN_SERVICE}


def _callback_message(callback: CallbackQuery) -> Message | None:
    message = callback.message
    return message if isinstance(message, Message) else None


def _format_money(amount: Decimal) -> str:
    return f"{amount:.2f} ₽"


def _parse_amount(text: str) -> Decimal | None:
    cleaned = text.strip().replace(" ", "").replace(",", ".")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if value <= 0:
        return None
    return value.quantize(Decimal("0.01"))


async def _show_cash(callback: CallbackQuery, session: AsyncSession) -> None:
    rows = await sellers_repo.list_balances(session)
    if not rows:
        text = (
            "Кассы пустые: сначала добавь продавцов в Сервис → Управление → Продавцы.\n"
            "В кассе считается выручка с продаж плюс/минус переводы."
        )
    else:
        lines = [
            "Кассы продавцов (выручка с продаж ± переводы):",
            "",
        ]
        lines.extend(f"• {seller.name}: {_format_money(balance)}" for seller, balance in rows)
        if all(balance == 0 for _, balance in rows):
            lines.extend(
                [
                    "",
                    "Пока продаж нет, кассы нулевые — переводить нечего.",
                ]
            )
        text = "\n".join(lines)
    message = _callback_message(callback)
    if message:
        await message.edit_text(text, reply_markup=cash_menu(rows))


@router.callback_query(NavCB.filter(F.to == "accounting"))
async def open_cash(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await _show_cash(callback, session)


@router.callback_query(ManageCB.filter((F.section == "cash") & (F.action == "from")))
async def pick_from(callback: CallbackQuery, session: AsyncSession) -> None:
    sellers = await sellers_repo.list_sellers(session)
    if len(sellers) < 2:
        await callback.answer("Нужно минимум двое продавцов.", show_alert=True)
        return
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.edit_text(
            "От кого перевести?",
            reply_markup=pick_seller_keyboard(sellers, "pick_from"),
        )


@router.callback_query(ManageCB.filter((F.section == "cash") & (F.action == "pick_from")))
async def picked_from(
    callback: CallbackQuery,
    callback_data: ManageCB,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.update_data(from_seller_id=callback_data.item_id)
    sellers = await sellers_repo.list_sellers(session)
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.edit_text(
            "Кому перевести?",
            reply_markup=pick_seller_keyboard(
                sellers,
                "pick_to",
                skip_id=callback_data.item_id,
            ),
        )


@router.callback_query(ManageCB.filter((F.section == "cash") & (F.action == "pick_to")))
async def picked_to(
    callback: CallbackQuery,
    callback_data: ManageCB,
    state: FSMContext,
) -> None:
    await state.update_data(to_seller_id=callback_data.item_id)
    await state.set_state(TransferCash.amount)
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.answer("Напиши сумму перевода. /cancel — отмена.")


@router.message(TransferCash.amount, F.text, ~F.text.in_(MENU_TEXTS))
async def save_transfer(message: Message, state: FSMContext, session: AsyncSession) -> None:
    amount = _parse_amount(message.text or "")
    if amount is None:
        await message.answer("Нужна сумма больше нуля, например 1500 или 1500.50")
        return
    data = await state.get_data()
    from_id = data.get("from_seller_id")
    to_id = data.get("to_seller_id")
    if not isinstance(from_id, int) or not isinstance(to_id, int):
        await state.clear()
        await message.answer("Сессия сбилась. Открой Бухгалтерию заново.")
        return
    source = await sellers_repo.get_seller(session, from_id)
    target = await sellers_repo.get_seller(session, to_id)
    if source is None or target is None:
        await state.clear()
        await message.answer("Продавец не найден. Открой Бухгалтерию заново.")
        return
    try:
        await sellers_repo.transfer(session, from_id, to_id, amount)
    except InsufficientFundsError:
        await message.answer("Недостаточно денег у отправителя.")
        return
    except InUseError:
        await message.answer("Нельзя перевести самому себе.")
        return
    await state.clear()
    rows = await sellers_repo.list_balances(session)
    lines = [
        f"Перевод {_format_money(amount)}: {source.name} → {target.name}.",
        "",
        "Кассы сейчас:",
    ]
    lines.extend(f"• {seller.name}: {_format_money(balance)}" for seller, balance in rows)
    await message.answer("\n".join(lines), reply_markup=cash_menu(rows))
