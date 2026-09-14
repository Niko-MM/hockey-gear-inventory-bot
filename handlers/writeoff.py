# pyright: reportUnusedCallResult=false
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Batch, City, ColorOption, CurveOption, FlexOption, GripOption, StickModel
from keyboards.callbacks import NavCB, WriteoffCB
from keyboards.menu import BTN_INCOME, BTN_SALE, BTN_SERVICE, BTN_STOCK
from keyboards.service import service_menu
from keyboards.writeoff import choice_keyboard, confirm_keyboard, qty_keyboard
from repositories import catalog
from repositories import stock
from repositories.sales import OutOfStockError
from repositories.writeoffs import create_writeoff
from states.writeoff import WriteOffFlow
from utils.money import format_money

router = Router()

MENU_TEXTS = {BTN_SALE, BTN_INCOME, BTN_STOCK, BTN_SERVICE}

ID_KEY = {
    "city": "city_id",
    "flex": "flex_id",
    "grip": "grip_id",
    "curve": "curve_id",
    "batch": "batch_id",
    "qty": "quantity",
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
        "quantity",
        "saw_qty_step",
    ),
    "model": (
        "flex_id",
        "grip_id",
        "curve_id",
        "batch_id",
        "saw_batch_step",
        "quantity",
        "saw_qty_step",
    ),
    "flex": (
        "grip_id",
        "curve_id",
        "batch_id",
        "saw_batch_step",
        "quantity",
        "saw_qty_step",
    ),
    "grip": (
        "curve_id",
        "batch_id",
        "saw_batch_step",
        "quantity",
        "saw_qty_step",
    ),
    "curve": (
        "batch_id",
        "saw_batch_step",
        "quantity",
        "saw_qty_step",
    ),
    "batch": ("quantity", "saw_qty_step"),
    "qty": (),
}

EMPTY_HINT = {
    "city": "Остатков нет. Нечего списывать.",
    "model": "В этом городе нет клюшек.",
    "flex": "Нет флекса в остатке.",
    "grip": "Нет хвата в остатке.",
    "curve": "Нет загиба в остатке.",
    "batch": "Нет партии в остатке.",
}

PROMPT = {
    "city": "Какой город?",
    "model": "Какая модель?",
    "flex": "Какой флекс?",
    "grip": "Какой хват?",
    "curve": "Какой загиб?",
    "batch": "Какая партия?",
    "qty": "Сколько штук списать?",
}


def _callback_message(callback: CallbackQuery) -> Message | None:
    message = callback.message
    return message if isinstance(message, Message) else None


def _color_title(color: ColorOption) -> str:
    if color.is_default:
        return f"{color.name} (классика)"
    return color.name


def _with_qty(title: str, qty: int) -> str:
    return f"{title} — {qty} шт"


def _card(progress: str) -> str:
    return progress.removeprefix("Списание").strip()


def _int_data(data: dict, key: str) -> int | None:
    value = data.get(key)
    return value if isinstance(value, int) else None


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


async def _progress_lines(session: AsyncSession, data: dict) -> str:
    lines = ["Списание"]
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
            lines.append(f"Закуп: {format_money(batch.purchase_price)}")
    quantity = _int_data(data, "quantity")
    if quantity is not None:
        lines.append(f"Количество: {quantity}")
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
                f"{format_money(batch.purchase_price)} · остаток {batch.remaining_quantity}",
            )
            for batch in batches
        ]
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


async def _batch_remaining(session: AsyncSession, data: dict) -> int:
    batch_id = _int_data(data, "batch_id")
    if batch_id is None:
        return 0
    batch = await session.get(Batch, batch_id)
    if batch is None:
        return 0
    return batch.remaining_quantity


async def _resolve_qty(session: AsyncSession, state: FSMContext) -> str:
    data = await state.get_data()
    remaining = await _batch_remaining(session, data)
    if remaining <= 1:
        await state.update_data(quantity=1, saw_qty_step=False)
        return "confirm"
    await state.update_data(saw_qty_step=True)
    return "qty"


async def _resolve_step(session: AsyncSession, state: FSMContext, step: str) -> str:
    if step == "batch":
        data = await state.get_data()
        batches = await _batches_for_data(session, data)
        if len(batches) == 1:
            await state.update_data(batch_id=batches[0].id, saw_batch_step=False)
            return await _resolve_qty(session, state)
        if len(batches) > 1:
            await state.update_data(saw_batch_step=True)
            return "batch"
        return "batch"
    if step == "qty":
        return await _resolve_qty(session, state)
    return step


def _back_step(data: dict, current: str) -> str | None:
    if current == "confirm":
        if data.get("saw_qty_step") is True:
            return "qty"
        return "batch" if data.get("saw_batch_step") is True else "curve"
    if current == "qty":
        return "batch" if data.get("saw_batch_step") is True else "curve"
    return {
        "model": "city",
        "flex": "model",
        "grip": "flex",
        "curve": "grip",
        "batch": "curve",
    }.get(current)


def _next_after_pick(step: str) -> str | None:
    return {
        "city": "model",
        "model": "flex",
        "flex": "grip",
        "grip": "curve",
        "curve": "batch",
        "batch": "qty",
        "qty": "confirm",
    }.get(step)


def _screen_text(
    progress: str,
    step: str,
    items: list[tuple[int, int, str]],
    remaining: int = 0,
) -> str:
    if step in EMPTY_HINT and not items:
        return f"{progress}\n\n{EMPTY_HINT[step]}"
    if step == "qty":
        extra = f" На партии {remaining}."
        if remaining > 10:
            extra += " Можно написать число."
        return f"{progress}\n\n{PROMPT[step]}{extra}"
    return f"{progress}\n\n{PROMPT[step]}"


def _keyboard(
    step: str,
    items: list[tuple[int, int, str]],
    remaining: int = 0,
) -> InlineKeyboardMarkup:
    if step == "qty":
        return qty_keyboard(remaining)
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
    if step == "qty":
        await state.set_state(WriteOffFlow.quantity)
    else:
        await state.set_state(None)

    data = await state.get_data()
    items = await _choices(session, step, data)
    remaining = await _batch_remaining(session, data) if step == "qty" else 0
    progress = await _progress_lines(session, data)
    if step == "confirm":
        text = f"{progress}\n\nКасса не изменится. Списать?"
    else:
        text = _screen_text(progress, step, items, remaining)
    markup = _keyboard(step, items, remaining)

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


@router.callback_query(NavCB.filter(F.to == "writeoff"))
async def open_writeoff(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await _show_step(session, state, "city", callback=callback)


@router.callback_query(WriteoffCB.filter(F.action == "cancel"))
async def cancel_writeoff(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.edit_text("Сервис", reply_markup=service_menu())


@router.callback_query(WriteoffCB.filter(F.action == "back"))
async def back_writeoff(
    callback: CallbackQuery,
    callback_data: WriteoffCB,
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


@router.callback_query(WriteoffCB.filter(F.action == "pick"))
async def pick_writeoff(
    callback: CallbackQuery,
    callback_data: WriteoffCB,
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
        if callback_data.step == "qty":
            remaining = await _batch_remaining(session, data)
            if callback_data.item_id < 1 or callback_data.item_id > remaining:
                await callback.answer("Столько на партии нет.", show_alert=True)
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


@router.message(WriteOffFlow.quantity, F.text, ~F.text.in_(MENU_TEXTS))
async def save_quantity(message: Message, state: FSMContext, session: AsyncSession) -> None:
    cleaned = (message.text or "").strip().replace(" ", "")
    if not cleaned.isdigit():
        await message.answer("Нужно целое число, например 3")
        return
    quantity = int(cleaned)
    data = await state.get_data()
    remaining = await _batch_remaining(session, data)
    if quantity < 1 or quantity > remaining:
        await message.answer(f"На партии {remaining} шт. Напиши число от 1 до {remaining}.")
        return
    data["quantity"] = quantity
    await state.set_data(data)
    await _show_step(session, state, "confirm", message=message, replace=True)


@router.callback_query(WriteoffCB.filter(F.action == "save"))
async def save_writeoff(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    batch_id = _int_data(data, "batch_id")
    quantity = _int_data(data, "quantity") or 1
    if batch_id is None:
        await callback.answer("Сессия сбилась. Начни списание заново.", show_alert=True)
        await state.clear()
        return
    try:
        await create_writeoff(session, batch_id=batch_id, quantity=quantity)
    except OutOfStockError:
        await callback.answer("На партии осталось меньше, чем нужно.", show_alert=True)
        return
    summary = await _progress_lines(session, data)
    await state.clear()
    await callback.answer()
    message = _callback_message(callback)
    if message:
        final = f"✅ Списал\n\n{_card(summary)}"
        try:
            await message.delete()
        except TelegramBadRequest:
            await message.edit_text(final, reply_markup=None)
            return
        await message.answer(final)
