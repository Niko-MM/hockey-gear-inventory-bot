# pyright: reportUnusedCallResult=false
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import City, ColorOption, CurveOption, FlexOption, GripOption
from keyboards.callbacks import StockCB
from keyboards.menu import BTN_STOCK
from keyboards.stock import back_keyboard, cities_keyboard, values_keyboard, view_menu_keyboard
from repositories import stock

router = Router()

TELEGRAM_TEXT_LIMIT = 3500
AXIS_TITLES = {
    "flex": "флекс",
    "grip": "хват",
    "curve": "загиб",
}


def _callback_message(callback: CallbackQuery) -> Message | None:
    message = callback.message
    return message if isinstance(message, Message) else None


def _color_title(color: ColorOption) -> str:
    if color.is_default:
        return f"{color.name} (классика)"
    return color.name


def _format_default(city_name: str, total: int, rows: list[tuple]) -> str:
    lines = [f"{city_name} — {total} шт"]
    current_group = ""
    for model, color, flex, grip, curve, qty in rows:
        group = f"{model.name} / {_color_title(color)}"
        if group != current_group:
            lines.append("")
            lines.append(group)
            current_group = group
        lines.append(f"• {flex.value} · {grip.name} · {curve.name} — {qty}")
    return "\n".join(lines)


def _format_filtered(header: str, axis: str, rows: list[tuple]) -> str:
    lines = [header]
    current_group = ""
    for model, color, flex, grip, curve, qty in rows:
        group = f"{model.name} / {_color_title(color)}"
        if group != current_group:
            lines.append("")
            lines.append(group)
            current_group = group
        if axis == "flex":
            detail = f"{grip.name} · {curve.name}"
        elif axis == "grip":
            detail = f"{flex.value} · {curve.name}"
        else:
            detail = f"{flex.value} · {grip.name}"
        lines.append(f"• {detail} — {qty}")
    return "\n".join(lines)


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


async def _send_text(
    callback: CallbackQuery,
    text: str,
    markup: InlineKeyboardMarkup | None,
) -> None:
    message = _callback_message(callback)
    if not message:
        return
    chunks = _chunks(text)
    first_markup = markup if len(chunks) == 1 else None
    await message.edit_text(chunks[0], reply_markup=first_markup)
    for index, chunk in enumerate(chunks[1:], start=2):
        last = index == len(chunks)
        await message.answer(chunk, reply_markup=markup if last else None)


async def _show_cities(
    session: AsyncSession,
    *,
    callback: CallbackQuery | None = None,
    message: Message | None = None,
) -> None:
    rows = await stock.cities_with_stock(session)
    if not rows:
        text = "Остатков нет. Сначала внеси поступление."
        markup = None
    else:
        text = "Остатки. Выбери город."
        markup = cities_keyboard(rows)
    target = _callback_message(callback) if callback else None
    if target:
        await target.edit_text(text, reply_markup=markup)
        return
    if message:
        await message.answer(text, reply_markup=markup)


async def _show_menu(callback: CallbackQuery, session: AsyncSession, city_id: int) -> None:
    city = await session.get(City, city_id)
    if city is None:
        await callback.answer("Город не найден.", show_alert=True)
        return
    message = _callback_message(callback)
    if message:
        await message.edit_text(
            f"Остатки · {city.name}\n\nКак смотреть список?",
            reply_markup=view_menu_keyboard(city_id),
        )


async def _show_values(callback: CallbackQuery, session: AsyncSession, city_id: int, axis: str) -> None:
    city = await session.get(City, city_id)
    if city is None:
        await callback.answer("Город не найден.", show_alert=True)
        return
    if axis == "flex":
        raw = await stock.flexes_in_city(session, city_id)
        items = [(item.id, item.value, qty) for item, qty in raw]
        title = "флекс"
    elif axis == "grip":
        raw = await stock.grips_in_city(session, city_id)
        items = [(item.id, item.name, qty) for item, qty in raw]
        title = "хват"
    elif axis == "curve":
        raw = await stock.curves_in_city(session, city_id)
        items = [(item.id, item.name, qty) for item, qty in raw]
        title = "загиб"
    else:
        await callback.answer()
        return
    message = _callback_message(callback)
    if not message:
        return
    if not items:
        await message.edit_text(
            f"{city.name} — пусто.",
            reply_markup=view_menu_keyboard(city_id),
        )
        return
    await message.edit_text(
        f"{city.name}. Выбери {title}.",
        reply_markup=values_keyboard(city_id, axis, items),
    )


async def _show_view(
    callback: CallbackQuery,
    session: AsyncSession,
    city_id: int,
    axis: str,
    item_id: int,
) -> None:
    city = await session.get(City, city_id)
    if city is None:
        await callback.answer("Город не найден.", show_alert=True)
        return
    if axis == "default":
        rows = await stock.sku_with_stock(session, city_id)
        if not rows:
            text = f"{city.name} — пусто."
        else:
            total = sum(qty for *_, qty in rows)
            text = _format_default(city.name, total, rows)
        await _send_text(callback, text, back_keyboard(city_id))
        return

    filters: dict[str, int] = {}
    label = ""
    if axis == "flex":
        option = await session.get(FlexOption, item_id)
        if option is None:
            await callback.answer("Флекс не найден.", show_alert=True)
            return
        filters["flex_id"] = item_id
        label = option.value
    elif axis == "grip":
        option = await session.get(GripOption, item_id)
        if option is None:
            await callback.answer("Хват не найден.", show_alert=True)
            return
        filters["grip_id"] = item_id
        label = option.name
    elif axis == "curve":
        option = await session.get(CurveOption, item_id)
        if option is None:
            await callback.answer("Загиб не найден.", show_alert=True)
            return
        filters["curve_id"] = item_id
        label = option.name
    else:
        await callback.answer()
        return

    rows = await stock.sku_with_stock(session, city_id, **filters)
    axis_title = AXIS_TITLES[axis]
    if not rows:
        text = f"{city.name} · {axis_title} {label} — пусто."
    else:
        total = sum(qty for *_, qty in rows)
        header = f"{city.name} · {axis_title} {label} — {total} шт"
        text = _format_filtered(header, axis, rows)
    await _send_text(callback, text, back_keyboard(city_id, axis=axis))


@router.message(F.text == BTN_STOCK)
async def open_stock(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await _show_cities(session, message=message)


@router.callback_query(StockCB.filter(F.action == "cities"))
async def list_cities(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await _show_cities(session, callback=callback)


@router.callback_query(StockCB.filter(F.action == "menu"))
async def open_menu(
    callback: CallbackQuery,
    callback_data: StockCB,
    session: AsyncSession,
) -> None:
    await callback.answer()
    await _show_menu(callback, session, callback_data.city_id)


@router.callback_query(StockCB.filter(F.action == "values"))
async def open_values(
    callback: CallbackQuery,
    callback_data: StockCB,
    session: AsyncSession,
) -> None:
    await callback.answer()
    await _show_values(callback, session, callback_data.city_id, callback_data.axis)


@router.callback_query(StockCB.filter(F.action == "view"))
async def open_view(
    callback: CallbackQuery,
    callback_data: StockCB,
    session: AsyncSession,
) -> None:
    await callback.answer()
    await _show_view(
        callback,
        session,
        callback_data.city_id,
        callback_data.axis,
        callback_data.item_id,
    )
