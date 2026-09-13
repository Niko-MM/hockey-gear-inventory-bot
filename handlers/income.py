# pyright: reportUnusedCallResult=false
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import City, ColorOption, CurveOption, FlexOption, GripOption, StickModel
from keyboards.callbacks import IncomeCB
from keyboards.income import choice_keyboard, confirm_keyboard, nav_keyboard
from keyboards.menu import BTN_INCOME, BTN_SALE, BTN_SERVICE, BTN_STOCK
from repositories import batches as batches_repo
from repositories import catalog
from states.income import Income

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
    "city": ("model_id", "color_id", "flex_id", "curve_id", "grip_id", "quantity", "purchase_price"),
    "model": ("color_id", "flex_id", "curve_id", "grip_id", "quantity", "purchase_price"),
    "color": ("flex_id", "curve_id", "grip_id", "quantity", "purchase_price"),
    "flex": ("curve_id", "grip_id", "quantity", "purchase_price"),
    "curve": ("grip_id", "quantity", "purchase_price"),
    "grip": ("quantity", "purchase_price"),
}

EMPTY_HINT = {
    "city": "Городов нет.",
    "model": "Моделей нет. Добавь в Сервис → Управление.",
    "color": "Цветов нет. Добавь в Сервис → Управление.",
    "flex": "Флекса нет. Добавь в Сервис → Управление.",
    "curve": "Загибов нет. Добавь в Сервис → Управление.",
    "grip": "Хватов нет. Добавь в Сервис → Управление.",
}

PROMPT = {
    "city": "Выбери город.",
    "model": "Выбери модель.",
    "color": "Выбери цвет.",
    "flex": "Выбери флекс.",
    "curve": "Выбери загиб.",
    "grip": "Выбери хват.",
    "qty": "Напиши количество целым числом, например 3.",
    "price": "Напиши закупочную цену за штуку, например 12500 или 12500.50",
}


def _callback_message(callback: CallbackQuery) -> Message | None:
    message = callback.message
    return message if isinstance(message, Message) else None


def _format_money(amount: Decimal) -> str:
    return f"{amount:.2f} ₽"


def _parse_qty(text: str) -> int | None:
    cleaned = text.strip().replace(" ", "")
    if not cleaned.isdigit():
        return None
    value = int(cleaned)
    return value if value > 0 else None


def _parse_price(text: str) -> Decimal | None:
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
        lines.append(f"Закуп: {_format_money(price)} / шт")
        if isinstance(quantity, int):
            lines.append(f"Сумма закупа: {_format_money(price * quantity)}")
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
    return choice_keyboard(items, step, show_back=show_back)


async def _show_step(
    session: AsyncSession,
    state: FSMContext,
    step: str,
    *,
    callback: CallbackQuery | None = None,
    message: Message | None = None,
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
        text = f"{progress}\n\nЗаписать партию?"
    else:
        text = _screen_text(progress, step, items)
    markup = _keyboard(step, items)

    target = _callback_message(callback) if callback else None
    if target:
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc):
                await target.answer(text, reply_markup=markup)
        return
    if message:
        await message.answer(text, reply_markup=markup)


@router.message(F.text == BTN_INCOME)
async def open_income(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await _show_step(session, state, "city", message=message)


@router.callback_query(IncomeCB.filter(F.action == "cancel"))
async def cancel_income(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.edit_text("Отменено. Главное меню.")


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
    await _show_step(session, state, "price", message=message)


@router.message(Income.price, F.text, ~F.text.in_(MENU_TEXTS))
async def save_price(message: Message, state: FSMContext, session: AsyncSession) -> None:
    price = _parse_price(message.text or "")
    if price is None:
        await message.answer("Нужна цена больше нуля, например 12500 или 12500.50")
        return
    await state.update_data(purchase_price=str(price))
    await _show_step(session, state, "confirm", message=message)


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
        cities = [(city.id, city.name) for city in await batches_repo.list_cities(session)]
        await message.edit_text(
            f"Записал партию.\n\n{summary}\n\nЕщё одно поступление — выбери город.",
            reply_markup=choice_keyboard(cities, "city", show_back=False),
        )
