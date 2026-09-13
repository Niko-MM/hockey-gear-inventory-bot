# pyright: reportUnusedCallResult=false
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import City, ColorOption
from keyboards.callbacks import StockCB
from keyboards.menu import BTN_STOCK
from keyboards.stock import cities_keyboard, city_stock_keyboard
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


def _format_city_stock(
    city_name: str,
    total: int,
    rows: list[tuple],
) -> str:
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


async def _show_city(callback: CallbackQuery, session: AsyncSession, city_id: int) -> None:
    city = await session.get(City, city_id)
    if city is None:
        await callback.answer("Город не найден.", show_alert=True)
        return
    rows = await stock.sku_with_stock(session, city_id)
    if not rows:
        text = f"{city.name} — пусто."
    else:
        total = sum(qty for *_, qty in rows)
        text = _format_city_stock(city.name, total, rows)
    message = _callback_message(callback)
    if not message:
        return
    chunks = _chunks(text)
    await message.edit_text(chunks[0], reply_markup=city_stock_keyboard() if len(chunks) == 1 else None)
    for index, chunk in enumerate(chunks[1:], start=2):
        last = index == len(chunks)
        await message.answer(chunk, reply_markup=city_stock_keyboard() if last else None)


@router.message(F.text == BTN_STOCK)
async def open_stock(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await _show_cities(session, message=message)


@router.callback_query(StockCB.filter(F.action == "cities"))
async def list_cities(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await _show_cities(session, callback=callback)


@router.callback_query(StockCB.filter(F.action == "city"))
async def show_city(
    callback: CallbackQuery,
    callback_data: StockCB,
    session: AsyncSession,
) -> None:
    await callback.answer()
    await _show_city(callback, session, callback_data.item_id)
