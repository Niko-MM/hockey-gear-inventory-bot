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
    from utils.labels import color_title

    return color_title(color)


def _format_stock(header: str, rows: list[tuple], *, hide: frozenset[str]) -> str:
    lines = [header]
    current_group = ""
    for model, color, flex, grip, curve, qty in rows:
        group = f"{model.name} / {_color_title(color)}"
        bits: list[str] = []
        if "flex" not in hide:
            bits.append(flex.value)
        if "grip" not in hide:
            bits.append(grip.name)
        if "curve" not in hide:
            bits.append(curve.name)
        if not bits:
            if group != current_group:
                lines.append("")
            lines.append(f"{group} — {qty}")
            current_group = group
            continue
        if group != current_group:
            lines.append("")
            lines.append(group)
            current_group = group
        lines.append(f"• {' · '.join(bits)} — {qty}")
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


async def _selected_flex_ids(state: FSMContext) -> list[int]:
    data = await state.get_data()
    raw = data.get("stock_flex_ids")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, int)]


async def _clear_flex_ids(state: FSMContext) -> None:
    await state.update_data(stock_flex_ids=[])


async def _show_cities(
    session: AsyncSession,
    *,
    callback: CallbackQuery | None = None,
    message: Message | None = None,
) -> None:
    rows = await stock.cities_with_stock(session)
    if not rows:
        text = "В наличии ничего нет. Сначала поступление."
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
    total = sum(qty for _, _, qty in items)
    await message.edit_text(
        f"{city.name}. Какой хват?",
        reply_markup=grips_keyboard(city_id, items, total),
    )


async def _show_all(callback: CallbackQuery, session: AsyncSession, city_id: int) -> None:
    city = await session.get(City, city_id)
    if city is None:
        await callback.answer("Город не найден.", show_alert=True)
        return
    rows = await stock.sku_with_stock(session, city_id)
    if not rows:
        message = _callback_message(callback)
        if message:
            await message.edit_text(
                f"{city.name} — пусто.",
                reply_markup=back_to_cities_keyboard(),
            )
        return
    total = sum(qty for *_, qty in rows)
    text = _format_stock(f"{city.name} — {total} шт", rows, hide=frozenset())
    await _send_text(callback, text, back_keyboard(city_id))


async def _show_flexes(
    callback: CallbackQuery,
    session: AsyncSession,
    city_id: int,
    grip_id: int,
    state: FSMContext,
) -> None:
    city = await session.get(City, city_id)
    grip = await session.get(GripOption, grip_id)
    if city is None or grip is None:
        await callback.answer("Не найдено.", show_alert=True)
        return
    raw = await stock.flexes_in_city(session, city_id, grip_id=grip_id)
    items = [(item.id, item.value, qty) for item, qty in raw]
    stored = await _selected_flex_ids(state)
    selected = [item_id for item_id, _, _ in items if item_id in set(stored)]
    if selected != stored:
        await state.update_data(stock_flex_ids=selected)
    rows = await stock.sku_with_stock(
        session,
        city_id,
        grip_id=grip_id,
        flex_ids=selected or None,
    )
    if not items or not rows:
        message = _callback_message(callback)
        if message:
            grips = await stock.grips_in_city(session, city_id)
            grip_items = [(item.id, item.name, qty) for item, qty in grips]
            await message.edit_text(
                f"{city.name} · {grip.name} — пусто.",
                reply_markup=grips_keyboard(
                    city_id,
                    grip_items,
                    sum(qty for _, _, qty in grip_items),
                ),
            )
        return
    curve_items: list[tuple[int, str, int]] = []
    if selected:
        curve_items = [
            (item.id, item.name, qty)
            for item, qty in await stock.curves_in_city(
                session,
                city_id,
                grip_id=grip_id,
                flex_ids=selected,
            )
        ]
    header = f"{city.name} · {grip.name}"
    titles = [title for item_id, title, _ in items if item_id in set(selected)]
    if titles:
        header = f"{header} · {', '.join(titles)}"
    total = sum(qty for *_, qty in rows)
    hide = {"grip", "flex"} if len(selected) == 1 else {"grip"}
    prompt = "Какой загиб?" if selected else "Какой флекс? Можно отметить несколько."
    text = _format_stock(f"{header} — {total} шт", rows, hide=frozenset(hide))
    await _send_text(
        callback,
        f"{text}\n\n{prompt}",
        flexes_keyboard(
            city_id,
            grip_id,
            items,
            selected=selected,
            curves=curve_items,
        ),
    )


async def _show_view(
    callback: CallbackQuery,
    session: AsyncSession,
    city_id: int,
    grip_id: int,
    curve_id: int,
    state: FSMContext,
    *,
    flex_id: int = 0,
) -> None:
    city = await session.get(City, city_id)
    if city is None:
        await callback.answer("Город не найден.", show_alert=True)
        return

    flex_ids = await _selected_flex_ids(state)
    if not flex_ids and flex_id:
        flex_ids = [flex_id]
    if not grip_id or not curve_id or not flex_ids:
        await callback.answer("Не найдено.", show_alert=True)
        return

    grip = await session.get(GripOption, grip_id)
    curve = await session.get(CurveOption, curve_id)
    flexes: list[FlexOption] = []
    for item_id in flex_ids:
        flex = await session.get(FlexOption, item_id)
        if flex is not None:
            flexes.append(flex)
    if grip is None or curve is None or not flexes:
        await callback.answer("Не найдено.", show_alert=True)
        return
    flexes.sort(key=lambda item: item.value)

    rows = await stock.sku_with_stock(
        session,
        city_id,
        grip_id=grip_id,
        flex_ids=[item.id for item in flexes],
        curve_id=curve_id,
    )
    flex_label = ", ".join(item.value for item in flexes)
    header_bits = f"{city.name} · {grip.name} · {flex_label} · {curve.name}"
    hide = {"grip", "curve"}
    if len(flexes) == 1:
        hide.add("flex")
    if not rows:
        text = f"{header_bits} — пусто."
    else:
        total = sum(qty for *_, qty in rows)
        text = _format_stock(
            f"{header_bits} — {total} шт",
            rows,
            hide=frozenset(hide),
        )
    await _send_text(callback, text, back_keyboard(city_id, grip_id=grip_id))


@router.message(F.text == BTN_STOCK)
async def open_stock(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await _show_cities(session, message=message)


@router.callback_query(StockCB.filter(F.action == "cities"))
async def list_cities(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    await _clear_flex_ids(state)
    await _show_cities(session, callback=callback)


@router.callback_query(StockCB.filter(F.action == "grips"))
async def open_grips(
    callback: CallbackQuery,
    callback_data: StockCB,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    await callback.answer()
    await _clear_flex_ids(state)
    await _show_grips(callback, session, callback_data.city_id)


@router.callback_query(StockCB.filter(F.action == "all"))
async def open_all(
    callback: CallbackQuery,
    callback_data: StockCB,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    await callback.answer()
    await _clear_flex_ids(state)
    await _show_all(callback, session, callback_data.city_id)


@router.callback_query(StockCB.filter(F.action == "flexes"))
async def open_flexes(
    callback: CallbackQuery,
    callback_data: StockCB,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    await callback.answer()
    await _show_flexes(callback, session, callback_data.city_id, callback_data.grip_id, state)


@router.callback_query(StockCB.filter(F.action == "pick_flex"))
async def pick_flex(
    callback: CallbackQuery,
    callback_data: StockCB,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    await callback.answer()
    flex_id = callback_data.flex_id
    selected = await _selected_flex_ids(state)
    if flex_id in selected:
        selected = [item for item in selected if item != flex_id]
    else:
        selected = [*selected, flex_id]
    await state.update_data(stock_flex_ids=selected)
    await _show_flexes(callback, session, callback_data.city_id, callback_data.grip_id, state)


@router.callback_query(StockCB.filter(F.action == "curves"))
async def open_curves(
    callback: CallbackQuery,
    callback_data: StockCB,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    await callback.answer()
    if callback_data.flex_id:
        await state.update_data(stock_flex_ids=[callback_data.flex_id])
    await _show_flexes(callback, session, callback_data.city_id, callback_data.grip_id, state)


@router.callback_query(StockCB.filter(F.action == "view"))
async def open_view(
    callback: CallbackQuery,
    callback_data: StockCB,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    await callback.answer()
    await _show_view(
        callback,
        session,
        callback_data.city_id,
        callback_data.grip_id,
        callback_data.curve_id,
        state,
        flex_id=callback_data.flex_id,
    )
