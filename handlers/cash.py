# pyright: reportUnusedCallResult=false
from datetime import date
from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from keyboards.callbacks import ManageCB, NavCB
from keyboards.cash import (
    cash_menu,
    cash_nav_keyboard,
    deposit_confirm_keyboard,
    pick_seller_keyboard,
    report_end_keyboard,
    report_keyboard,
    withdraw_confirm_keyboard,
)
from keyboards.menu import BTN_INCOME, BTN_SALE, BTN_SERVICE, BTN_STOCK
from repositories import reports as reports_repo
from repositories import sellers as sellers_repo
from repositories.catalog import InUseError
from repositories.sellers import InsufficientFundsError
from states.sellers import DepositCash, ReportPeriod, TransferCash, WithdrawCash
from utils.dates import format_input_date, format_range, parse_date, today
from utils.money import format_money, parse_money

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


def _cheques(n: int) -> str:
    n100 = abs(n) % 100
    n10 = n100 % 10
    if 11 <= n100 <= 14:
        word = "чеков"
    elif n10 == 1:
        word = "чек"
    elif 2 <= n10 <= 4:
        word = "чека"
    else:
        word = "чеков"
    return f"{n} {word}"


def _format_report(report: reports_repo.PeriodReport) -> str:
    lines = [format_range(report.start, report.end)]
    has_sales = report.total_qty > 0 or report.receipts > 0
    has_other = bool(
        report.incoming_by_city
        or report.transfers
        or report.withdrawals_by_seller
        or report.writeoffs_by_city
        or report.wholesale_by_seller
    )
    if not has_sales and not has_other:
        lines.extend(["", "За этот период ничего не было."])
        return "\n".join(lines)

    if has_sales:
        lines.extend(["", "Продажи"])
        lines.extend(f"{name} — {qty} шт" for name, qty in report.cities)
        lines.append(f"Всего — {report.total_qty} шт · {_cheques(report.receipts)}")
        if report.sales_by_model:
            lines.extend(["", "Модели"])
            lines.extend(f"{name} — {qty} шт" for name, qty in report.sales_by_model)
        lines.extend(
            [
                "",
                "Деньги",
                f"Выручка — {format_money(report.revenue)}",
                f"Закуп — {format_money(report.cost)}",
                f"Прибыль — {format_money(report.profit)}",
            ]
        )
        if report.receipts:
            lines.append(f"Средний чек — {format_money(report.revenue / report.receipts)}")
        if len(report.sales_by_city) > 1:
            for city in report.sales_by_city:
                lines.extend(["", city.name])
                lines.extend(f"{model} — {qty} шт" for model, qty in city.models)
                lines.extend(
                    [
                        f"Выручка — {format_money(city.revenue)}",
                        f"Закуп — {format_money(city.cost)}",
                        f"Прибыль — {format_money(city.profit)}",
                    ]
                )

    if report.wholesale_by_seller:
        lines.extend(["", "Опт"])
        lines.extend(
            f"{name} — {format_money(amount)}"
            for name, amount in report.wholesale_by_seller
        )
        lines.append(f"Всего — {format_money(report.wholesale_total)}")

    if has_sales:
        if report.sales_by_seller:
            lines.extend(["", "Кассы (пришло с продаж)"])
            lines.extend(
                f"{name} — {format_money(amount)} · {qty} шт"
                for name, amount, qty in report.sales_by_seller
            )

    if report.incoming_by_city:
        lines.extend(["", "Поступило на склад"])
        lines.extend(
            f"{name} — {qty} шт · закуп {format_money(amount)}"
            for name, qty, amount in report.incoming_by_city
        )

    if report.transfers:
        lines.extend(["", "Переводы"])
        lines.extend(
            f"{source} → {target} — {format_money(amount)}"
            for source, target, amount in report.transfers
        )

    if report.withdrawals_by_seller:
        lines.extend(["", "Забрали"])
        lines.extend(
            f"{name} — {format_money(amount)}"
            for name, amount in report.withdrawals_by_seller
        )

    if report.writeoffs_by_city:
        lines.extend(["", "Списали"])
        lines.extend(
            f"{name} — {qty} шт · закуп {format_money(amount)}"
            for name, qty, amount in report.writeoffs_by_city
        )
    return "\n".join(lines)


def _cash_text(rows: list) -> str:
    if not rows:
        return "Касс нет. Добавь продавцов: Сервис → Справочник → Продавцы."
    lines = ["Кассы", ""]
    lines.extend(f"{seller.name} — {format_money(balance)}" for seller, balance in rows)
    total = sum((balance for _, balance in rows), Decimal("0"))
    lines.append("")
    lines.append(f"Всего — {format_money(total)}")
    return "\n".join(lines)


async def _show_cash(
    session: AsyncSession,
    *,
    callback: CallbackQuery | None = None,
    message: Message | None = None,
) -> None:
    rows = await sellers_repo.list_balances(session)
    text = _cash_text(rows)
    markup = cash_menu(rows)
    target = _callback_message(callback) if callback else None
    if target:
        await target.edit_text(text, reply_markup=markup)
        return
    if message:
        await message.answer(text, reply_markup=markup)


@router.callback_query(NavCB.filter(F.to == "accounting"))
async def open_cash(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await _show_cash(session, callback=callback)


@router.callback_query(ManageCB.filter((F.section == "cash") & (F.action == "cancel")))
async def cancel_cash(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await _show_cash(session, callback=callback)


@router.callback_query(ManageCB.filter((F.section == "cash") & (F.action == "from")))
async def pick_from(callback: CallbackQuery, session: AsyncSession) -> None:
    sellers = await sellers_repo.list_sellers(session)
    if len(sellers) < 2:
        await callback.answer("Нужно двое продавцов.", show_alert=True)
        return
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.edit_text("От кого?", reply_markup=pick_seller_keyboard(sellers, "pick_from"))


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
            "Кому?",
            reply_markup=pick_seller_keyboard(sellers, "pick_to", skip_id=callback_data.item_id),
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
        await message.edit_text("Сколько перевести?", reply_markup=cash_nav_keyboard())
        await _remember_prompt(state, message)


@router.message(TransferCash.amount, F.text, ~F.text.in_(MENU_TEXTS))
async def save_transfer(message: Message, state: FSMContext, session: AsyncSession) -> None:
    amount = parse_money(message.text or "")
    if amount is None:
        await message.answer("Нужно целое число, например 20 000")
        return
    data = await state.get_data()
    from_id = data.get("from_seller_id")
    to_id = data.get("to_seller_id")
    if not isinstance(from_id, int) or not isinstance(to_id, int):
        await state.clear()
        await message.answer("Начни перевод заново.")
        return
    source = await sellers_repo.get_seller(session, from_id)
    target = await sellers_repo.get_seller(session, to_id)
    if source is None or target is None:
        await state.clear()
        await message.answer("Продавец не найден.")
        return
    try:
        await sellers_repo.transfer(session, from_id, to_id, amount)
    except InsufficientFundsError:
        await message.answer(f"У {source.name} только {format_money(await sellers_repo.seller_balance(session, from_id))}.")
        return
    except InUseError:
        await message.answer("Нельзя перевести себе.")
        return
    await _delete_prompt(message.bot, state)
    await state.clear()
    rows = await sellers_repo.list_balances(session)
    lines = [
        f"✅ Перевёл {format_money(amount)}: {source.name} → {target.name}",
        "",
        _cash_text(rows),
    ]
    await message.answer("\n".join(lines), reply_markup=cash_menu(rows))


@router.callback_query(ManageCB.filter((F.section == "cash") & (F.action == "withdraw")))
async def pick_withdraw(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    sellers = await sellers_repo.list_sellers(session)
    if not sellers:
        await callback.answer("Сначала добавь продавцов.", show_alert=True)
        return
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.edit_text("У кого забрать?", reply_markup=pick_seller_keyboard(sellers, "pick_wd"))


@router.callback_query(ManageCB.filter((F.section == "cash") & (F.action == "pick_wd")))
async def picked_withdraw(
    callback: CallbackQuery,
    callback_data: ManageCB,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    seller = await sellers_repo.get_seller(session, callback_data.item_id)
    if seller is None:
        await callback.answer("Продавец не найден.", show_alert=True)
        return
    await state.update_data(withdraw_seller_id=seller.id)
    await state.set_state(WithdrawCash.amount)
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.edit_text(f"Сколько забрать у {seller.name}?", reply_markup=cash_nav_keyboard())
        await _remember_prompt(state, message)


@router.message(WithdrawCash.amount, F.text, ~F.text.in_(MENU_TEXTS))
async def confirm_withdraw(message: Message, state: FSMContext, session: AsyncSession) -> None:
    amount = parse_money(message.text or "")
    if amount is None:
        await message.answer("Нужно целое число, например 50 000")
        return
    data = await state.get_data()
    seller_id = data.get("withdraw_seller_id")
    if not isinstance(seller_id, int):
        await state.clear()
        await message.answer("Начни заново.")
        return
    seller = await sellers_repo.get_seller(session, seller_id)
    if seller is None:
        await state.clear()
        await message.answer("Продавец не найден.")
        return
    balance = await sellers_repo.seller_balance(session, seller.id)
    if amount > balance:
        await message.answer(f"У {seller.name} только {format_money(balance)}.")
        return
    await state.update_data(withdraw_amount=str(amount))
    await state.set_state(None)
    await _delete_prompt(message.bot, state)
    sent = await message.answer(
        f"Забрать {format_money(amount)} у {seller.name}?",
        reply_markup=withdraw_confirm_keyboard(),
    )
    await _remember_prompt(state, sent)


@router.callback_query(ManageCB.filter((F.section == "cash") & (F.action == "save_wd")))
async def save_withdraw(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    seller_id = data.get("withdraw_seller_id")
    raw_amount = data.get("withdraw_amount")
    if not isinstance(seller_id, int) or not isinstance(raw_amount, str):
        await callback.answer("Начни заново.", show_alert=True)
        await state.clear()
        return
    seller = await sellers_repo.get_seller(session, seller_id)
    if seller is None:
        await callback.answer("Продавец не найден.", show_alert=True)
        await state.clear()
        return
    amount = Decimal(raw_amount)
    try:
        await sellers_repo.withdraw(session, seller_id, amount)
    except InsufficientFundsError:
        balance = await sellers_repo.seller_balance(session, seller_id)
        await callback.answer(f"У {seller.name} только {format_money(balance)}.", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    rows = await sellers_repo.list_balances(session)
    text = f"✅ Забрал {format_money(amount)} у {seller.name}\n\n{_cash_text(rows)}"
    message = _callback_message(callback)
    if message:
        try:
            await message.delete()
        except TelegramBadRequest:
            await message.edit_text(text, reply_markup=cash_menu(rows))
            return
        await message.answer(text, reply_markup=cash_menu(rows))


@router.callback_query(ManageCB.filter((F.section == "cash") & (F.action == "deposit")))
async def pick_deposit(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    sellers = await sellers_repo.list_sellers(session)
    if not sellers:
        await callback.answer("Сначала добавь продавцов.", show_alert=True)
        return
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.edit_text("Кому зачислить?", reply_markup=pick_seller_keyboard(sellers, "pick_dep"))


@router.callback_query(ManageCB.filter((F.section == "cash") & (F.action == "pick_dep")))
async def picked_deposit(
    callback: CallbackQuery,
    callback_data: ManageCB,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    seller = await sellers_repo.get_seller(session, callback_data.item_id)
    if seller is None:
        await callback.answer("Продавец не найден.", show_alert=True)
        return
    await state.update_data(deposit_seller_id=seller.id)
    await state.set_state(DepositCash.amount)
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.edit_text(
            f"Сколько зачислить {seller.name}? Это опт.",
            reply_markup=cash_nav_keyboard(),
        )
        await _remember_prompt(state, message)


@router.message(DepositCash.amount, F.text, ~F.text.in_(MENU_TEXTS))
async def confirm_deposit(message: Message, state: FSMContext, session: AsyncSession) -> None:
    amount = parse_money(message.text or "")
    if amount is None:
        await message.answer("Нужно целое число, например 40 000")
        return
    data = await state.get_data()
    seller_id = data.get("deposit_seller_id")
    if not isinstance(seller_id, int):
        await state.clear()
        await message.answer("Начни заново.")
        return
    seller = await sellers_repo.get_seller(session, seller_id)
    if seller is None:
        await state.clear()
        await message.answer("Продавец не найден.")
        return
    await state.update_data(deposit_amount=str(amount))
    await state.set_state(None)
    await _delete_prompt(message.bot, state)
    sent = await message.answer(
        f"Зачислить {format_money(amount)} {seller.name} как опт?",
        reply_markup=deposit_confirm_keyboard(),
    )
    await _remember_prompt(state, sent)


@router.callback_query(ManageCB.filter((F.section == "cash") & (F.action == "save_dep")))
async def save_deposit(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    seller_id = data.get("deposit_seller_id")
    raw_amount = data.get("deposit_amount")
    if not isinstance(seller_id, int) or not isinstance(raw_amount, str):
        await callback.answer("Начни заново.", show_alert=True)
        await state.clear()
        return
    seller = await sellers_repo.get_seller(session, seller_id)
    if seller is None:
        await callback.answer("Продавец не найден.", show_alert=True)
        await state.clear()
        return
    amount = Decimal(raw_amount)
    try:
        await sellers_repo.deposit(session, seller_id, amount)
    except InsufficientFundsError:
        await callback.answer("Не получилось зачислить.", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    rows = await sellers_repo.list_balances(session)
    text = f"✅ Зачислил (опт) {format_money(amount)} · {seller.name}\n\n{_cash_text(rows)}"
    message = _callback_message(callback)
    if message:
        try:
            await message.delete()
        except TelegramBadRequest:
            await message.edit_text(text, reply_markup=cash_menu(rows))
            return
        await message.answer(text, reply_markup=cash_menu(rows))


def _report_start_prompt() -> str:
    return f"С какого числа? Сегодня {format_input_date(today())}"


def _report_end_prompt() -> str:
    return f"По какое число? Сегодня {format_input_date(today())}"


async def _finish_report(
    session: AsyncSession,
    state: FSMContext,
    start: date,
    end: date,
    *,
    message: Message | None = None,
    callback: CallbackQuery | None = None,
) -> None:
    report = await reports_repo.period_report(session, start, end)
    text = _format_report(report)
    markup = report_keyboard()
    if callback:
        await state.clear()
        await callback.answer()
        target = _callback_message(callback)
        if target:
            await target.edit_text(text, reply_markup=markup)
        return
    if message:
        await _delete_prompt(message.bot, state)
        await state.clear()
        await message.answer(text, reply_markup=markup)


@router.callback_query(ManageCB.filter((F.section == "cash") & (F.action == "report")))
async def start_report(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ReportPeriod.start)
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.edit_text(_report_start_prompt(), reply_markup=cash_nav_keyboard())
        await _remember_prompt(state, message)


@router.message(ReportPeriod.start, F.text, ~F.text.in_(MENU_TEXTS))
async def save_report_start(message: Message, state: FSMContext) -> None:
    start = parse_date(message.text or "")
    if start is None:
        await message.answer(f"Напиши дату так: {format_input_date(today())}")
        return
    await state.update_data(report_start=start.isoformat())
    await state.set_state(ReportPeriod.end)
    await _delete_prompt(message.bot, state)
    sent = await message.answer(_report_end_prompt(), reply_markup=report_end_keyboard())
    await _remember_prompt(state, sent)


@router.message(ReportPeriod.end, F.text, ~F.text.in_(MENU_TEXTS))
async def save_report_end(message: Message, state: FSMContext, session: AsyncSession) -> None:
    end = parse_date(message.text or "")
    if end is None:
        await message.answer(f"Напиши дату так: {format_input_date(today())}")
        return
    data = await state.get_data()
    raw_start = data.get("report_start")
    if not isinstance(raw_start, str):
        await state.clear()
        await message.answer("Начни отчёт заново.")
        return
    start = date.fromisoformat(raw_start)
    if start > end:
        await message.answer("Начало позже конца. Напиши ещё раз.")
        return
    await _finish_report(session, state, start, end, message=message)


@router.callback_query(
    ReportPeriod.end,
    ManageCB.filter((F.section == "cash") & (F.action == "report_today")),
)
async def report_today(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    raw_start = data.get("report_start")
    if not isinstance(raw_start, str):
        await callback.answer("Начни отчёт заново.", show_alert=True)
        await state.clear()
        return
    start = date.fromisoformat(raw_start)
    end = today()
    if start > end:
        await callback.answer("Начало позже сегодня. Напиши дату конца.", show_alert=True)
        return
    await _finish_report(session, state, start, end, callback=callback)
