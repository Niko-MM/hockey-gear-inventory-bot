# pyright: reportUnusedCallResult=false
from decimal import Decimal, InvalidOperation

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Batch, City, ColorOption, CurveOption, FlexOption, GripOption, StickModel
from keyboards.callbacks import SaleCB
from keyboards.menu import BTN_INCOME, BTN_SALE, BTN_SERVICE, BTN_STOCK
from keyboards.sale import choice_keyboard, confirm_keyboard, nav_keyboard
from repositories import catalog
from repositories import sellers as sellers_repo
from repositories import stock
from repositories.sales import OutOfStockError, create_sale
from states.sale import SaleFlow

router = Router()

MENU_TEXTS = {BTN_SALE, BTN_INCOME, BTN_STOCK, BTN_SERVICE}

ID_KEY = {
    "city": "city_id",
    "flex": "flex_id",
    "grip": "grip_id",
    "curve": "curve_id",
    "batch": "batch_id",
    "seller": "seller_id",
}

CLEAR_AFTER = {
    "city": (
        "model_id",
        "color_id",
        "flex_id",
        "grip_id",
        "curve_id",
        "batch_id",
        "saw_batch_step",
        "total_amount",
        "seller_id",
    ),
    "model": (
        "flex_id",
        "grip_id",
        "curve_id",
        "batch_id",
        "saw_batch_step",
        "total_amount",
        "seller_id",
    ),
    "flex": ("grip_id", "curve_id", "batch_id", "saw_batch_step", "total_amount", "seller_id"),
    "grip": ("curve_id", "batch_id", "saw_batch_step", "total_amount", "seller_id"),
    "curve": ("batch_id", "saw_batch_step", "total_amount", "seller_id"),
    "batch": ("total_amount", "seller_id"),
    "seller": (),
}

EMPTY_HINT = {
    "city": "Остатков нет. Сначала внеси поступление.",
    "model": "В этом городе нет клюшек.",
    "flex": "Нет флекса в остатке.",
    "grip": "Нет хвата в остатке.",
    "curve": "Нет загиба в остатке.",
    "batch": "Нет партии в остатке.",
    "seller": "Продавцов нет. Добавь в Сервис → Управление.",
}

PROMPT = {
    "city": "Выбери город.",
    "model": "Выбери модель и цвет.",
    "flex": "Выбери флекс.",
    "grip": "Выбери хват.",
    "curve": "Выбери загиб.",
    "batch": "Выбери партию по закупу.",
    "amount": "Напиши сумму чека за эту клюшку, например 18000 или 18000.50",
    "seller": "У кого осели деньги?",
}


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


def _color_title(color: ColorOption) -> str:
    if color.is_default:
        return f"{color.name} (классика)"
    return color.name


def _with_qty(title: str, qty: int) -> str:
    return f"{title} — {qty} шт"


def _receipt(progress: str) -> str:
    return progress.removeprefix("Продажа").strip()


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


def _int_data(data: dict, key: str) -> int | None:
    value = data.get(key)
    return value if isinstance(value, int) else None


async def _progress_lines(session: AsyncSession, data: dict) -> str:
    lines = ["Продажа"]
    city_id = _int_data(data, "city_id")
    if city_id is not None:
        city = await session.get(City, city_id)
        if city:
            lines.append(f"Город: {city.name}")
    model_id = _int_data(data, "model_id")
    if model_id is not None:
        model = await session.get(StickModel, model_id)
        if model:
            lines.append(f"Модель: {model.name}")
    color_id = _int_data(data, "color_id")
    if color_id is not None:
        color = await session.get(ColorOption, color_id)
        if color:
            lines.append(f"Цвет: {_color_title(color)}")
    flex_id = _int_data(data, "flex_id")
    if flex_id is not None:
        flex = await session.get(FlexOption, flex_id)
        if flex:
            lines.append(f"Флекс: {flex.value}")
    grip_id = _int_data(data, "grip_id")
    if grip_id is not None:
        grip = await session.get(GripOption, grip_id)
        if grip:
            lines.append(f"Хват: {grip.name}")
    curve_id = _int_data(data, "curve_id")
    if curve_id is not None:
        curve = await session.get(CurveOption, curve_id)
        if curve:
            lines.append(f"Загиб: {curve.name}")
    batch_id = _int_data(data, "batch_id")
    if batch_id is not None:
        batch = await session.get(Batch, batch_id)
        if batch:
            lines.append(f"Закуп: {_format_money(Decimal(batch.purchase_price))}")
    raw_amount = data.get("total_amount")
    if isinstance(raw_amount, str):
        lines.append(f"Сумма чека: {_format_money(Decimal(raw_amount))}")
    seller_id = _int_data(data, "seller_id")
    if seller_id is not None:
        seller = await sellers_repo.get_seller(session, seller_id)
        if seller:
            lines.append(f"Деньги у: {seller.name}")
    return "\n".join(lines)


async def _choices(
    session: AsyncSession,
    step: str,
    data: dict,
) -> list[tuple[int, int, str]]:
    city_id = _int_data(data, "city_id")
    model_id = _int_data(data, "model_id")
    color_id = _int_data(data, "color_id")
    flex_id = _int_data(data, "flex_id")
    grip_id = _int_data(data, "grip_id")

    if step == "city":
        return [
            (city.id, 0, _with_qty(city.name, qty))
            for city, qty in await stock.cities_with_stock(session)
        ]
    if step == "model" and city_id is not None:
        return [
            (model.id, color.id, _with_qty(f"{model.name} / {_color_title(color)}", qty))
            for model, color, qty in await stock.model_colors_with_stock(session, city_id)
        ]
    if step == "flex" and city_id is not None and model_id is not None and color_id is not None:
        return [
            (item.id, 0, _with_qty(item.value, qty))
            for item, qty in await stock.flex_with_stock(
                session,
                city_id=city_id,
                model_id=model_id,
                color_id=color_id,
            )
        ]
    if (
        step == "grip"
        and city_id is not None
        and model_id is not None
        and color_id is not None
        and flex_id is not None
    ):
        return [
            (item.id, 0, _with_qty(item.name, qty))
            for item, qty in await stock.grips_with_stock(
                session,
                city_id=city_id,
                model_id=model_id,
                color_id=color_id,
                flex_id=flex_id,
            )
        ]
    if (
        step == "curve"
        and city_id is not None
        and model_id is not None
        and color_id is not None
        and flex_id is not None
        and grip_id is not None
    ):
        return [
            (item.id, 0, _with_qty(item.name, qty))
            for item, qty in await stock.curves_with_stock(
                session,
                city_id=city_id,
                model_id=model_id,
                color_id=color_id,
                flex_id=flex_id,
                grip_id=grip_id,
            )
        ]
    if step == "batch":
        batches = await _batches_for_data(session, data)
        return [
            (
                batch.id,
                0,
                f"{_format_money(Decimal(batch.purchase_price))} · остаток {batch.remaining_quantity}",
            )
            for batch in batches
        ]
    if step == "seller":
        return [(seller.id, 0, seller.name) for seller in await sellers_repo.list_sellers(session)]
    return []


async def _batches_for_data(session: AsyncSession, data: dict) -> list[Batch]:
    city_id = _int_data(data, "city_id")
    model_id = _int_data(data, "model_id")
    color_id = _int_data(data, "color_id")
    flex_id = _int_data(data, "flex_id")
    curve_id = _int_data(data, "curve_id")
    grip_id = _int_data(data, "grip_id")
    if (
        city_id is None
        or model_id is None
        or color_id is None
        or flex_id is None
        or curve_id is None
        or grip_id is None
    ):
        return []
    product = await catalog.find_product(
        session,
        model_id=model_id,
        color_id=color_id,
        flex_id=flex_id,
        curve_id=curve_id,
        grip_id=grip_id,
    )
    if product is None:
        return []
    return await stock.batches_in_stock(session, city_id=city_id, product_id=product.id)


async def _resolve_step(session: AsyncSession, state: FSMContext, step: str) -> str:
    if step != "batch":
        return step
    data = await state.get_data()
    batches = await _batches_for_data(session, data)
    if len(batches) == 1:
        await state.update_data(batch_id=batches[0].id, saw_batch_step=False)
        return "amount"
    if len(batches) > 1:
        await state.update_data(saw_batch_step=True)
        return "batch"
    return "batch"


def _back_step(data: dict, current: str) -> str | None:
    if current == "amount":
        return "batch" if data.get("saw_batch_step") is True else "curve"
    mapping = {
        "model": "city",
        "flex": "model",
        "grip": "flex",
        "curve": "grip",
        "batch": "curve",
        "seller": "amount",
        "confirm": "seller",
    }
    return mapping.get(current)


def _next_after_pick(step: str) -> str | None:
    return {
        "city": "model",
        "model": "flex",
        "flex": "grip",
        "grip": "curve",
        "curve": "batch",
        "batch": "amount",
        "seller": "confirm",
    }.get(step)


def _screen_text(progress: str, step: str, items: list[tuple[int, int, str]]) -> str:
    if step in EMPTY_HINT and not items:
        return f"{progress}\n\n{EMPTY_HINT[step]}"
    return f"{progress}\n\n{PROMPT[step]}"


def _keyboard(step: str, items: list[tuple[int, int, str]]) -> InlineKeyboardMarkup:
    if step == "amount":
        return nav_keyboard(step, show_back=True)
    if step == "confirm":
        return confirm_keyboard()
    return choice_keyboard(items, step, show_back=step != "city")


async def _show_step(
    session: AsyncSession,
    state: FSMContext,
    step: str,
    *,
    callback: CallbackQuery | None = None,
    message: Message | None = None,
    replace: bool = False,
) -> None:
    step = await _resolve_step(session, state, step)
    if step == "amount":
        await state.set_state(SaleFlow.amount)
    else:
        await state.set_state(None)

    data = await state.get_data()
    items = await _choices(session, step, data)
    progress = await _progress_lines(session, data)
    if step == "confirm":
        text = f"{progress}\n\nЗаписать продажу?"
    else:
        text = _screen_text(progress, step, items)
    markup = _keyboard(step, items)

    target = _callback_message(callback) if callback else None
    if target and not replace:
        try:
            await target.edit_text(text, reply_markup=markup)
            await _remember_prompt(state, target)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                await _remember_prompt(state, target)
                return
            await _delete_prompt(target.bot, state)
            sent = await target.answer(text, reply_markup=markup)
            await _remember_prompt(state, sent)
            return
    if message:
        if replace:
            await _delete_prompt(message.bot, state)
        sent = await message.answer(text, reply_markup=markup)
        await _remember_prompt(state, sent)


@router.message(F.text == BTN_SALE)
async def open_sale(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _delete_prompt(message.bot, state)
    await state.clear()
    await _show_step(session, state, "city", message=message)


@router.callback_query(SaleCB.filter(F.action == "cancel"))
async def cancel_sale(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.edit_text("Отменено. Главное меню.")


@router.callback_query(SaleCB.filter(F.action == "back"))
async def back_sale(
    callback: CallbackQuery,
    callback_data: SaleCB,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    previous = _back_step(data, callback_data.step)
    if previous is None:
        await callback.answer()
        return
    await callback.answer()
    await _show_step(session, state, previous, callback=callback)


@router.callback_query(SaleCB.filter(F.action == "pick"))
async def pick_sale(
    callback: CallbackQuery,
    callback_data: SaleCB,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    if callback_data.step == "model":
        if not callback_data.item_id or not callback_data.extra_id:
            await callback.answer("Некорректный выбор.", show_alert=True)
            return
        color = await session.get(ColorOption, callback_data.extra_id)
        if color is None or color.model_id != callback_data.item_id:
            await callback.answer("Этот цвет не от выбранной модели.", show_alert=True)
            return
        for stale in CLEAR_AFTER["model"]:
            data.pop(stale, None)
        data["model_id"] = callback_data.item_id
        data["color_id"] = callback_data.extra_id
    else:
        key = ID_KEY.get(callback_data.step)
        if key is None or not callback_data.item_id:
            await callback.answer("Некорректный выбор.", show_alert=True)
            return
        if callback_data.step == "batch":
            batches = await _batches_for_data(session, data)
            if callback_data.item_id not in {batch.id for batch in batches}:
                await callback.answer("Этой партии уже нет в остатке.", show_alert=True)
                return
        if callback_data.step == "seller":
            seller = await sellers_repo.get_seller(session, callback_data.item_id)
            if seller is None:
                await callback.answer("Продавец не найден.", show_alert=True)
                return
        for stale in CLEAR_AFTER.get(callback_data.step, ()):
            data.pop(stale, None)
        data[key] = callback_data.item_id
    await state.set_data(data)
    nxt = _next_after_pick(callback_data.step)
    if nxt is None:
        await callback.answer()
        return
    await callback.answer()
    await _show_step(session, state, nxt, callback=callback)


@router.message(SaleFlow.amount, F.text, ~F.text.in_(MENU_TEXTS))
async def save_amount(message: Message, state: FSMContext, session: AsyncSession) -> None:
    amount = _parse_amount(message.text or "")
    if amount is None:
        await message.answer("Нужна сумма больше нуля, например 18000 или 18000.50")
        return
    await state.update_data(total_amount=str(amount))
    await _show_step(session, state, "seller", message=message, replace=True)


@router.callback_query(SaleCB.filter(F.action == "save"))
async def save_sale(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    batch_id = _int_data(data, "batch_id")
    seller_id = _int_data(data, "seller_id")
    raw_amount = data.get("total_amount")
    if batch_id is None or seller_id is None or not isinstance(raw_amount, str):
        await callback.answer("Сессия сбилась. Начни продажу заново.", show_alert=True)
        await state.clear()
        return
    try:
        await create_sale(
            session,
            batch_id=batch_id,
            seller_id=seller_id,
            total_amount=Decimal(raw_amount),
        )
    except OutOfStockError:
        await callback.answer("Этой клюшки уже нет в остатке.", show_alert=True)
        return
    summary = await _progress_lines(session, data)
    await state.clear()
    await callback.answer()
    message = _callback_message(callback)
    if message:
        final = (
            f"✅ Продажа записана\n\n{_receipt(summary)}\n\n"
            "Чтобы оформить ещё — Продажа."
        )
        try:
            await message.delete()
        except TelegramBadRequest:
            await message.edit_text(final, reply_markup=None)
            return
        await message.answer(final)
