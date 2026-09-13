# pyright: reportUnusedCallResult=false
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import City, ColorOption, CurveOption, FlexOption, GripOption
from keyboards.callbacks import StockCB
from keyboards.menu import BTN_STOCK
from keyboards.stock import (
    back_keyboard,
    back_to_cities_keyboard,
    cities_keyboard,
    curves_keyboard,
    flexes_keyboard,
    grips_keyboard,
)
from repositories import stock

router = Router()

TELEGRAM_TEXT_LIMIT = 3500


def _callback_message(callback: CallbackQuery) -> Message | None:
    message = callback.message
    return message if isinstance(message, Message) else None


def _color_title(color: ColorOption) -> str:
    if color.is_default:
        return f"{color.name} (классика)"
    return color.name


def _format_all(city_name: str, total: int, rows: list[tuple]) -> str:
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


def _format_chain(header: str, rows: list[tuple]) -> str:
    lines = [header, ""]
    for model, color, *_rest, qty in rows:
        lines.append(f"{model.name} / {_color_title(color)} — {qty}")
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
        text = "Остатков нет. Сначала поступление."
        markup = None
    else:
        text = "Какой город?"
        markup = cities_keyboard(rows)
    target = _callback_message(callback) if callback else None
    if target:
        await target.edit_text(text, reply_markup=markup)
        return
    if message:
        await message.answer(text, reply_markup=markup)


async def _show_grips(callback: CallbackQuery, session: AsyncSession, city_id: int) -> None:
    city = await session.get(City, city_id)
    if city is None:
        await callback.answer("Город не найден.", show_alert=True)
        return
    raw = await stock.grips_in_city(session, city_id)
    items = [(item.id, item.name, qty) for item, qty in raw]
    message = _callback_message(callback)
    if not message:
        return
    if not items:
        await message.edit_text(
            f"{city.name} — пусто.",
            reply_markup=back_to_cities_keyboard(),
        )
        return
    await message.edit_text(
        f"{city.name}. Какой хват?",
        reply_markup=grips_keyboard(city_id, items),
    )


async def _show_flexes(
    callback: CallbackQuery,
    session: AsyncSession,
    city_id: int,
    grip_id: int,
) -> None:
    city = await session.get(City, city_id)
    grip = await session.get(GripOption, grip_id)
    if city is None or grip is None:
        await callback.answer("Не найдено.", show_alert=True)
        return
    raw = await stock.flexes_in_city(session, city_id, grip_id=grip_id)
    items = [(item.id, item.value, qty) for item, qty in raw]
    message = _callback_message(callback)
    if not message:
        return
    if not items:
        await message.edit_text(
            f"{city.name} · {grip.name} — пусто.",
            reply_markup=grips_keyboard(
                city_id,
                [(item.id, item.name, qty) for item, qty in await stock.grips_in_city(session, city_id)],
            ),
        )
        return
    await message.edit_text(
        f"{city.name} · {grip.name}. Какой флекс?",
        reply_markup=flexes_keyboard(city_id, grip_id, items),
    )


async def _show_curves(
    callback: CallbackQuery,
    session: AsyncSession,
    city_id: int,
    grip_id: int,
    flex_id: int,
) -> None:
    city = await session.get(City, city_id)
    grip = await session.get(GripOption, grip_id)
    flex = await session.get(FlexOption, flex_id)
    if city is None or grip is None or flex is None:
        await callback.answer("Не найдено.", show_alert=True)
        return
    raw = await stock.curves_in_city(session, city_id, grip_id=grip_id, flex_id=flex_id)
    items = [(item.id, item.name, qty) for item, qty in raw]
    message = _callback_message(callback)
    if not message:
        return
    if not items:
        await message.edit_text(
            f"{city.name} · {grip.name} · {flex.value} — пусто.",
            reply_markup=flexes_keyboard(
                city_id,
                grip_id,
                [
                    (item.id, item.value, qty)
                    for item, qty in await stock.flexes_in_city(session, city_id, grip_id=grip_id)
                ],
            ),
        )
        return
    await message.edit_text(
        f"{city.name} · {grip.name} · {flex.value}. Какой загиб?",
        reply_markup=curves_keyboard(city_id, grip_id, flex_id, items),
    )


async def _show_view(
    callback: CallbackQuery,
    session: AsyncSession,
    city_id: int,
    grip_id: int,
    flex_id: int,
    curve_id: int,
) -> None:
    city = await session.get(City, city_id)
    if city is None:
        await callback.answer("Город не найден.", show_alert=True)
        return

    if not grip_id:
        rows = await stock.sku_with_stock(session, city_id)
        if not rows:
            text = f"{city.name} — пусто."
        else:
            total = sum(qty for *_, qty in rows)
            text = _format_all(city.name, total, rows)
        await _send_text(callback, text, back_keyboard(city_id))
        return

    grip = await session.get(GripOption, grip_id)
    flex = await session.get(FlexOption, flex_id)
    curve = await session.get(CurveOption, curve_id)
    if grip is None or flex is None or curve is None:
        await callback.answer("Не найдено.", show_alert=True)
        return

    rows = await stock.sku_with_stock(
        session,
        city_id,
        grip_id=grip_id,
        flex_id=flex_id,
        curve_id=curve_id,
    )
    header_bits = f"{city.name} · {grip.name} · {flex.value} · {curve.name}"
    if not rows:
        text = f"{header_bits} — пусто."
    else:
        total = sum(qty for *_, qty in rows)
        text = _format_chain(f"{header_bits} — {total} шт", rows)
    await _send_text(callback, text, back_keyboard(city_id, grip_id=grip_id, flex_id=flex_id))


@router.message(F.text == BTN_STOCK)
async def open_stock(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await _show_cities(session, message=message)


@router.callback_query(StockCB.filter(F.action == "cities"))
async def list_cities(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await _show_cities(session, callback=callback)


@router.callback_query(StockCB.filter(F.action == "grips"))
async def open_grips(
    callback: CallbackQuery,
    callback_data: StockCB,
    session: AsyncSession,
) -> None:
    await callback.answer()
    await _show_grips(callback, session, callback_data.city_id)


@router.callback_query(StockCB.filter(F.action == "flexes"))
async def open_flexes(
    callback: CallbackQuery,
    callback_data: StockCB,
    session: AsyncSession,
) -> None:
    await callback.answer()
    await _show_flexes(callback, session, callback_data.city_id, callback_data.grip_id)


@router.callback_query(StockCB.filter(F.action == "curves"))
async def open_curves(
    callback: CallbackQuery,
    callback_data: StockCB,
    session: AsyncSession,
) -> None:
    await callback.answer()
    await _show_curves(
        callback,
        session,
        callback_data.city_id,
        callback_data.grip_id,
        callback_data.flex_id,
    )


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
        callback_data.grip_id,
        callback_data.flex_id,
        callback_data.curve_id,
    )
