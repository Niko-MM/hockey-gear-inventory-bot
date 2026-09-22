# pyright: reportUnusedCallResult=false
from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.models import City, ColorOption, CurveOption, FlexOption, GripOption, StickModel
from keyboards.callbacks import IncomeCB
from keyboards.income import (
    choice_keyboard,
    confirm_keyboard,
    nav_keyboard,
    sheet_error_keyboard,
    sheet_preview_keyboard,
)
from keyboards.menu import BTN_INCOME, BTN_SALE, BTN_SERVICE, BTN_STOCK
from repositories import batches as batches_repo
from repositories import catalog
from repositories import sheet_income as sheet_repo
from states.income import Income
from utils.money import format_money, parse_money

router = Router()

MENU_TEXTS = {BTN_SALE, BTN_INCOME, BTN_STOCK, BTN_SERVICE}

NEXT_STEP = {
    "city": "model",
    "model": "color",
    "color": "flex",
    "flex": "curve",
    "curve": "grip",
    "grip": "qty",
}

BACK_STEP = {
    "model": "city",
    "color": "model",
    "flex": "color",
    "curve": "flex",
    "grip": "curve",
    "qty": "grip",
    "price": "qty",
    "confirm": "price",
    "sheet": "model",
}

ID_KEY = {
    "city": "city_id",
    "model": "model_id",
    "color": "color_id",
    "flex": "flex_id",
    "curve": "curve_id",
    "grip": "grip_id",
}

CLEAR_AFTER = {
    "city": ("model_id", "color_id", "flex_id", "curve_id", "grip_id", "quantity", "purchase_price", "sheet_batches"),
    "model": ("color_id", "flex_id", "curve_id", "grip_id", "quantity", "purchase_price", "sheet_batches"),
    "color": ("flex_id", "curve_id", "grip_id", "quantity", "purchase_price"),
    "flex": ("curve_id", "grip_id", "quantity", "purchase_price"),
    "curve": ("grip_id", "quantity", "purchase_price"),
    "grip": ("quantity", "purchase_price"),
}

EMPTY_HINT = {
    "city": "Городов нет.",
    "model": "Моделей нет. Добавь в Сервис → Номенклатура.",
    "color": "Цветов нет. Добавь в Сервис → Номенклатура.",
    "flex": "Флекса нет. Добавь в Сервис → Номенклатура.",
    "curve": "Загибов нет. Добавь в Сервис → Номенклатура.",
    "grip": "Хватов нет. Добавь в Сервис → Номенклатура.",
}

PROMPT = {
    "city": "Какой город?",
    "model": "Какая модель?",
    "color": "Какой цвет?",
    "flex": "Какой флекс?",
    "curve": "Какой загиб?",
    "grip": "Какой хват?",
    "qty": "Сколько клюшек? Например 3",
    "price": "Закуп одной? Например 12 500",
}


def _callback_message(callback: CallbackQuery) -> Message | None:
    message = callback.message
    return message if isinstance(message, Message) else None


def _parse_qty(text: str) -> int | None:
    cleaned = text.strip().replace(" ", "")
    if not cleaned.isdigit():
        return None
    value = int(cleaned)
    return value if value > 0 else None


def _color_title(color: ColorOption) -> str:
    from utils.labels import color_title

    return color_title(color)


async def _progress_lines(session: AsyncSession, data: dict) -> str:
    lines = ["Поступление"]
    city_id = data.get("city_id")
    if isinstance(city_id, int):
        city = await session.get(City, city_id)
        if city:
            lines.append(f"Город: {city.name}")
    model_id = data.get("model_id")
    if isinstance(model_id, int):
        model = await session.get(StickModel, model_id)
        if model:
            lines.append(f"Модель: {model.name}")
    color_id = data.get("color_id")
    if isinstance(color_id, int):
        color = await session.get(ColorOption, color_id)
        if color:
            lines.append(f"Цвет: {_color_title(color)}")
    flex_id = data.get("flex_id")
    if isinstance(flex_id, int):
        flex = await session.get(FlexOption, flex_id)
        if flex:
            lines.append(f"Флекс: {flex.value}")
    curve_id = data.get("curve_id")
    if isinstance(curve_id, int):
        curve = await session.get(CurveOption, curve_id)
        if curve:
            lines.append(f"Загиб: {curve.name}")
    grip_id = data.get("grip_id")
    if isinstance(grip_id, int):
        grip = await session.get(GripOption, grip_id)
        if grip:
            lines.append(f"Хват: {grip.name}")
    quantity = data.get("quantity")
    if isinstance(quantity, int):
        lines.append(f"Количество: {quantity}")
    raw_price = data.get("purchase_price")
    if isinstance(raw_price, str):
        price = Decimal(raw_price)
        lines.append(f"Закуп: {format_money(price)} / шт")
        if isinstance(quantity, int):
            lines.append(f"Сумма закупа: {format_money(price * quantity)}")
    return "\n".join(lines)


async def _choices(
    session: AsyncSession,
    step: str,
    data: dict,
) -> list[tuple[int, str]]:
    if step == "city":
        return [(city.id, city.name) for city in await batches_repo.list_cities(session)]
    if step == "model":
        return [(model.id, model.name) for model in await catalog.list_models(session)]
    if step == "color":
        model_id = data.get("model_id")
        if not isinstance(model_id, int):
            return []
        return [
            (color.id, _color_title(color))
            for color in await catalog.list_colors(session, model_id)
        ]
    if step == "flex":
        return [(item.id, item.value) for item in await catalog.list_flex(session)]
    if step == "curve":
        return [(item.id, item.name) for item in await catalog.list_curves(session)]
    if step == "grip":
        return [(item.id, item.name) for item in await catalog.list_grips(session)]
    return []


def _screen_text(progress: str, step: str, items: list[tuple[int, str]]) -> str:
    if step in EMPTY_HINT and not items:
        return f"{progress}\n\n{EMPTY_HINT[step]}"
    return f"{progress}\n\n{PROMPT[step]}"


def _keyboard(step: str, items: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    show_back = step != "city"
    if step in {"qty", "price"}:
        return nav_keyboard(step, show_back=True)
    if step == "confirm":
        return confirm_keyboard()
    extras: list[InlineKeyboardButton] = []
    if step == "model" and settings.income_sheet_url.strip():
        extras.append(
            InlineKeyboardButton(
                text="Из таблицы",
                callback_data=IncomeCB(action="sheet", step="model").pack(),
            )
        )
    return choice_keyboard(items, step, show_back=show_back, extras=extras)


def _receipt(progress: str) -> str:
    return progress.removeprefix("Поступление").strip()


TELEGRAM_TEXT_LIMIT = 3500


def _chunks(text: str) -> list[str]:
    if len(text) <= TELEGRAM_TEXT_LIMIT:
        return [text]
    parts: list[str] = []
    buf: list[str] = []
    size = 0
    for line in text.split("\n"):
        extra = len(line) + (1 if buf else 0)
        if buf and size + extra > TELEGRAM_TEXT_LIMIT:
            parts.append("\n".join(buf))
            buf = [line]
            size = len(line)
        else:
            buf.append(line)
            size += extra
    if buf:
        parts.append("\n".join(buf))
    return parts


async def _edit_long(
    callback: CallbackQuery,
    text: str,
    markup: InlineKeyboardMarkup | None,
    state: FSMContext,
) -> None:
    message = _callback_message(callback)
    if not message:
        return
    chunks = _chunks(text)
    first_markup = markup if len(chunks) == 1 else None
    try:
        await message.edit_text(chunks[0], reply_markup=first_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise
    await _remember_prompt(state, message)
    for index, chunk in enumerate(chunks[1:], start=2):
        last = index == len(chunks)
        sent = await message.answer(chunk, reply_markup=markup if last else None)
        if last:
            await _remember_prompt(state, sent)


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


async def _show_step(
    session: AsyncSession,
    state: FSMContext,
    step: str,
    *,
    callback: CallbackQuery | None = None,
    message: Message | None = None,
    replace: bool = False,
) -> None:
    if step == "qty":
        await state.set_state(Income.quantity)
    elif step == "price":
        await state.set_state(Income.price)
    else:
        await state.set_state(None)

    data = await state.get_data()
    items = await _choices(session, step, data)
    progress = await _progress_lines(session, data)
    if step == "confirm":
        text = f"{progress}\n\nЗаписать?"
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


@router.message(F.text == BTN_INCOME)
async def open_income(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _delete_prompt(message.bot, state)
    await state.clear()
    await _show_step(session, state, "city", message=message)


@router.callback_query(IncomeCB.filter(F.action == "cancel"))
async def cancel_income(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.edit_text("Отменил.")


@router.callback_query(IncomeCB.filter(F.action == "back"))
async def back_income(
    callback: CallbackQuery,
    callback_data: IncomeCB,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    previous = BACK_STEP.get(callback_data.step)
    if previous is None:
        await callback.answer()
        return
    await callback.answer()
    await _show_step(session, state, previous, callback=callback)


@router.callback_query(IncomeCB.filter(F.action == "pick"))
async def pick_income(
    callback: CallbackQuery,
    callback_data: IncomeCB,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    key = ID_KEY.get(callback_data.step)
    if key is None or not callback_data.item_id:
        await callback.answer("Некорректный выбор.", show_alert=True)
        return
    data = await state.get_data()
    if callback_data.step == "color":
        model_id = data.get("model_id")
        color = await session.get(ColorOption, callback_data.item_id)
        if color is None or color.model_id != model_id:
            await callback.answer("Этот цвет не от выбранной модели.", show_alert=True)
            return
    for stale in CLEAR_AFTER.get(callback_data.step, ()):
        data.pop(stale, None)
    data[key] = callback_data.item_id
    await state.set_data(data)
    nxt = NEXT_STEP.get(callback_data.step)
    if nxt is None:
        await callback.answer()
        return
    await callback.answer()
    await _show_step(session, state, nxt, callback=callback)


@router.message(Income.quantity, F.text, ~F.text.in_(MENU_TEXTS))
async def save_quantity(message: Message, state: FSMContext, session: AsyncSession) -> None:
    quantity = _parse_qty(message.text or "")
    if quantity is None:
        await message.answer("Нужно целое число больше нуля, например 3.")
        return
    await state.update_data(quantity=quantity)
    await _show_step(session, state, "price", message=message, replace=True)


@router.message(Income.price, F.text, ~F.text.in_(MENU_TEXTS))
async def save_price(message: Message, state: FSMContext, session: AsyncSession) -> None:
    price = parse_money(message.text or "")
    if price is None:
        await message.answer("Нужно целое число, например 12 500")
        return
    await state.update_data(purchase_price=str(price))
    await _show_step(session, state, "confirm", message=message, replace=True)


@router.callback_query(IncomeCB.filter(F.action == "save"))
async def save_batch(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    city_id = data.get("city_id")
    model_id = data.get("model_id")
    color_id = data.get("color_id")
    flex_id = data.get("flex_id")
    curve_id = data.get("curve_id")
    grip_id = data.get("grip_id")
    quantity = data.get("quantity")
    raw_price = data.get("purchase_price")
    if (
        not isinstance(city_id, int)
        or not isinstance(model_id, int)
        or not isinstance(color_id, int)
        or not isinstance(flex_id, int)
        or not isinstance(curve_id, int)
        or not isinstance(grip_id, int)
        or not isinstance(quantity, int)
        or not isinstance(raw_price, str)
    ):
        await callback.answer("Сессия сбилась. Начни поступление заново.", show_alert=True)
        await state.clear()
        return
    price = Decimal(raw_price)
    product = await catalog.get_or_create_product(
        session,
        model_id=model_id,
        color_id=color_id,
        flex_id=flex_id,
        curve_id=curve_id,
        grip_id=grip_id,
    )
    await batches_repo.create_batch(
        session,
        product_id=product.id,
        city_id=city_id,
        quantity=quantity,
        purchase_price=price,
    )
    summary = await _progress_lines(session, data)
    await state.clear()
    await callback.answer()
    message = _callback_message(callback)
    if message:
        final = (
            f"✅ Принял\n\n{_receipt(summary)}"
        )
        try:
            await message.delete()
        except TelegramBadRequest:
            await message.edit_text(final, reply_markup=None)
            return
        await message.answer(final)


def _sheet_dump(batches: list[sheet_repo.SheetBatch]) -> list[dict]:
    return [
        {
            "model_id": item.model_id,
            "color_id": item.color_id,
            "flex_id": item.flex_id,
            "curve_id": item.curve_id,
            "grip_id": item.grip_id,
            "quantity": item.quantity,
            "purchase_price": str(item.purchase_price),
            "label": item.label,
        }
        for item in batches
    ]


@router.callback_query(IncomeCB.filter(F.action == "sheet"))
async def parse_sheet(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    url = settings.income_sheet_url.strip()
    if not url:
        await callback.answer("Ссылка на таблицу не задана.", show_alert=True)
        return
    data = await state.get_data()
    city_id = data.get("city_id")
    if not isinstance(city_id, int):
        await callback.answer("Сначала выбери город.", show_alert=True)
        return
    city = await session.get(City, city_id)
    if city is None:
        await callback.answer("Город не найден.", show_alert=True)
        return
    await callback.answer("Читаю таблицу…")
    preview = await sheet_repo.parse_income_sheet(session, url)
    if preview.errors:
        await state.update_data(sheet_batches=None)
        body = "\n".join(preview.errors)
        text = f"Поступление\nГород: {city.name}\n\nВ таблице ошибки, ничего не записал.\n\n{body}"
        await _edit_long(callback, text, sheet_error_keyboard(), state)
        return
    await state.update_data(sheet_batches=_sheet_dump(preview.batches))
    total_qty = sum(item.quantity for item in preview.batches)
    total_cost = sum((item.purchase_price * item.quantity for item in preview.batches), Decimal("0"))
    header = (
        f"Поступление\nГород: {city.name}\n\n"
        f"{len(preview.batches)} партий · {total_qty} шт · закуп {format_money(total_cost)}"
    )
    listing = "\n".join(item.label for item in preview.batches)
    text = f"{header}\n\n{listing}\n\nЗаписать?"
    await _edit_long(callback, text, sheet_preview_keyboard(), state)


@router.callback_query(IncomeCB.filter(F.action == "sheet_save"))
async def save_sheet(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    city_id = data.get("city_id")
    raw_batches = data.get("sheet_batches")
    if not isinstance(city_id, int) or not isinstance(raw_batches, list) or not raw_batches:
        await callback.answer("Сначала прочитай таблицу.", show_alert=True)
        return
    city = await session.get(City, city_id)
    created = 0
    total_qty = 0
    total_cost = Decimal("0")
    pack = None
    if len(raw_batches) > 1:
        pack = await batches_repo.create_income_import(session, city_id)
    import_id = pack.id if pack is not None else None
    for raw in raw_batches:
        if not isinstance(raw, dict):
            await callback.answer("Сессия сбилась. Начни поступление заново.", show_alert=True)
            await state.clear()
            return
        model_id = raw.get("model_id")
        color_id = raw.get("color_id")
        flex_id = raw.get("flex_id")
        curve_id = raw.get("curve_id")
        grip_id = raw.get("grip_id")
        quantity = raw.get("quantity")
        raw_price = raw.get("purchase_price")
        if (
            not isinstance(model_id, int)
            or not isinstance(color_id, int)
            or not isinstance(flex_id, int)
            or not isinstance(curve_id, int)
            or not isinstance(grip_id, int)
            or not isinstance(quantity, int)
            or not isinstance(raw_price, str)
        ):
            await callback.answer("Сессия сбилась. Начни поступление заново.", show_alert=True)
            await state.clear()
            return
        price = Decimal(raw_price)
        product = await catalog.get_or_create_product(
            session,
            model_id=model_id,
            color_id=color_id,
            flex_id=flex_id,
            curve_id=curve_id,
            grip_id=grip_id,
        )
        await batches_repo.create_batch(
            session,
            product_id=product.id,
            city_id=city_id,
            quantity=quantity,
            purchase_price=price,
            import_id=import_id,
        )
        created += 1
        total_qty += quantity
        total_cost += price * quantity
    city_name = city.name if city else "—"
    await state.clear()
    await callback.answer()
    message = _callback_message(callback)
    if message:
        final = (
            f"✅ Принял из таблицы\n\n"
            f"Город: {city_name}\n"
            f"{created} партий · {total_qty} шт · закуп {format_money(total_cost)}"
        )
        try:
            await message.delete()
        except TelegramBadRequest:
            await message.edit_text(final, reply_markup=None)
            return
        await message.answer(final)
