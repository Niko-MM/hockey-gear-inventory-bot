# pyright: reportUnusedCallResult=false
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from keyboards.callbacks import ManageCB
from keyboards.menu import BTN_INCOME, BTN_SALE, BTN_SERVICE, BTN_STOCK
from keyboards.service import (
    colors_keyboard,
    models_keyboard,
    named_options_keyboard,
    sellers_keyboard,
)
from repositories import catalog
from repositories import sellers as sellers_repo
from repositories.catalog import DuplicateNameError, InUseError
from states.catalog import AddColor, AddCurve, AddFlex, AddGrip, AddModel
from states.sellers import AddSeller

router = Router()

MENU_TEXTS = {BTN_SALE, BTN_INCOME, BTN_STOCK, BTN_SERVICE}
NOT_TEXT = "Нужно название текстом."


def _clean_name(text: str) -> str:
    return " ".join(text.split())


def _callback_message(callback: CallbackQuery) -> Message | None:
    message = callback.message
    return message if isinstance(message, Message) else None


async def _show_models(callback: CallbackQuery, session: AsyncSession) -> None:
    models = await catalog.list_models(session)
    text = "Модели. Нажми название, чтобы открыть цвета."
    if not models:
        text = "Моделей пока нет. Добавь первую — для конструктора поступления."
    message = _callback_message(callback)
    if message:
        await message.edit_text(text, reply_markup=models_keyboard(models))


async def _show_colors(
    callback: CallbackQuery, session: AsyncSession, model_id: int
) -> None:
    model = await catalog.get_model(session, model_id)
    if model is None:
        await callback.answer("Модель не найдена.", show_alert=True)
        return
    colors = await catalog.list_colors(session, model_id)
    message = _callback_message(callback)
    if message:
        await message.edit_text(
            f"Цвета модели «{model.name}».\n«Стандарт» нельзя удалить.",
            reply_markup=colors_keyboard(model_id, colors),
        )


@router.callback_query(ManageCB.filter((F.section == "model") & (F.action == "list")))
async def list_models(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await _show_models(callback, session)


@router.callback_query(ManageCB.filter((F.section == "model") & (F.action == "add")))
async def start_add_model(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddModel.name)
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.answer("Название модели?")


@router.message(AddModel.name, F.text, ~F.text.in_(MENU_TEXTS))
async def save_model(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    name = _clean_name(message.text or "")
    if not name:
        await message.answer(NOT_TEXT)
        return
    try:
        await catalog.create_model(session, name)
    except DuplicateNameError:
        await message.answer("Такая модель уже есть. Напиши другое название.")
        return
    await state.clear()
    models = await catalog.list_models(session)
    await message.answer(
        f"Модель «{name}» добавлена. «Стандарт» создан сам.",
        reply_markup=models_keyboard(models),
    )


@router.callback_query(ManageCB.filter((F.section == "model") & (F.action == "del")))
async def delete_model(
    callback: CallbackQuery,
    callback_data: ManageCB,
    session: AsyncSession,
) -> None:
    try:
        await catalog.delete_model(session, callback_data.item_id)
    except InUseError:
        await callback.answer(
            "Нельзя удалить: модель уже есть в товарах.", show_alert=True
        )
        return
    await callback.answer("Удалил.")
    await _show_models(callback, session)


@router.callback_query(ManageCB.filter((F.section == "color") & (F.action == "list")))
async def list_colors(
    callback: CallbackQuery,
    callback_data: ManageCB,
    session: AsyncSession,
) -> None:
    await callback.answer()
    await _show_colors(callback, session, callback_data.model_id)


@router.callback_query(ManageCB.filter((F.section == "color") & (F.action == "add")))
async def start_add_color(
    callback: CallbackQuery,
    callback_data: ManageCB,
    state: FSMContext,
) -> None:
    await state.set_state(AddColor.name)
    await state.update_data(model_id=callback_data.model_id)
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.answer("Название цвета?")


@router.message(AddColor.name, F.text, ~F.text.in_(MENU_TEXTS))
async def save_color(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    name = _clean_name(message.text or "")
    if not name:
        await message.answer(NOT_TEXT)
        return
    data = await state.get_data()
    raw_model_id = data.get("model_id")
    if not isinstance(raw_model_id, int):
        await state.clear()
        await message.answer("Открой Справочник заново.")
        return
    model_id = raw_model_id
    try:
        await catalog.create_color(session, model_id, name)
    except DuplicateNameError:
        await message.answer("Такой цвет у этой модели уже есть.")
        return
    await state.clear()
    model = await catalog.get_model(session, model_id)
    colors = await catalog.list_colors(session, model_id)
    title = model.name if model else "модель"
    await message.answer(
        f"Цвет «{name}» для «{title}» добавлен.",
        reply_markup=colors_keyboard(model_id, colors),
    )


@router.callback_query(ManageCB.filter((F.section == "color") & (F.action == "del")))
async def delete_color(
    callback: CallbackQuery,
    callback_data: ManageCB,
    session: AsyncSession,
) -> None:
    try:
        await catalog.delete_color(session, callback_data.item_id)
    except InUseError:
        await callback.answer(
            "Нельзя удалить: стандарт или цвет уже используется.",
            show_alert=True,
        )
        return
    await callback.answer("Удалил.")
    await _show_colors(callback, session, callback_data.model_id)


async def _show_flex(callback: CallbackQuery, session: AsyncSession) -> None:
    items = await catalog.list_flex(session)
    message = _callback_message(callback)
    if message:
        await message.edit_text(
            "Флекс (жёсткость).",
            reply_markup=named_options_keyboard("flex", items, "value"),
        )


async def _show_curves(callback: CallbackQuery, session: AsyncSession) -> None:
    items = await catalog.list_curves(session)
    message = _callback_message(callback)
    if message:
        await message.edit_text(
            "Загибы.",
            reply_markup=named_options_keyboard("curve", items, "name"),
        )


async def _show_grips(callback: CallbackQuery, session: AsyncSession) -> None:
    items = await catalog.list_grips(session)
    message = _callback_message(callback)
    if message:
        await message.edit_text(
            "Хваты.",
            reply_markup=named_options_keyboard("grip", items, "name"),
        )


@router.callback_query(ManageCB.filter((F.section == "flex") & (F.action == "list")))
async def list_flex(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await _show_flex(callback, session)


@router.callback_query(ManageCB.filter((F.section == "curve") & (F.action == "list")))
async def list_curves(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await _show_curves(callback, session)


@router.callback_query(ManageCB.filter((F.section == "grip") & (F.action == "list")))
async def list_grips(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await _show_grips(callback, session)


@router.callback_query(ManageCB.filter((F.section == "flex") & (F.action == "add")))
async def start_add_flex(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddFlex.value)
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.answer("Какой флекс? Например 87")


@router.callback_query(ManageCB.filter((F.section == "curve") & (F.action == "add")))
async def start_add_curve(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddCurve.name)
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.answer("Какой загиб?")


@router.callback_query(ManageCB.filter((F.section == "grip") & (F.action == "add")))
async def start_add_grip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddGrip.name)
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.answer("Какой хват? Например левый")


@router.message(AddFlex.value, F.text, ~F.text.in_(MENU_TEXTS))
async def save_flex(message: Message, state: FSMContext, session: AsyncSession) -> None:
    value = _clean_name(message.text or "")
    if not value:
        await message.answer(NOT_TEXT)
        return
    try:
        await catalog.create_flex(session, value)
    except DuplicateNameError:
        await message.answer("Такой флекс уже есть.")
        return
    await state.clear()
    items = await catalog.list_flex(session)
    await message.answer(
        "Флекс добавлен.", reply_markup=named_options_keyboard("flex", items, "value")
    )


@router.message(AddCurve.name, F.text, ~F.text.in_(MENU_TEXTS))
async def save_curve(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    name = _clean_name(message.text or "")
    if not name:
        await message.answer(NOT_TEXT)
        return
    try:
        await catalog.create_curve(session, name)
    except DuplicateNameError:
        await message.answer("Такой загиб уже есть.")
        return
    await state.clear()
    items = await catalog.list_curves(session)
    await message.answer(
        "Загиб добавлен.", reply_markup=named_options_keyboard("curve", items, "name")
    )


@router.message(AddGrip.name, F.text, ~F.text.in_(MENU_TEXTS))
async def save_grip(message: Message, state: FSMContext, session: AsyncSession) -> None:
    name = _clean_name(message.text or "")
    if not name:
        await message.answer(NOT_TEXT)
        return
    try:
        await catalog.create_grip(session, name)
    except DuplicateNameError:
        await message.answer("Такой хват уже есть.")
        return
    await state.clear()
    items = await catalog.list_grips(session)
    await message.answer(
        "Хват добавлен.", reply_markup=named_options_keyboard("grip", items, "name")
    )


@router.callback_query(ManageCB.filter((F.section == "flex") & (F.action == "del")))
async def delete_flex(
    callback: CallbackQuery,
    callback_data: ManageCB,
    session: AsyncSession,
) -> None:
    try:
        await catalog.delete_flex(session, callback_data.item_id)
    except InUseError:
        await callback.answer(
            "Нельзя удалить: флекс уже используется.", show_alert=True
        )
        return
    await callback.answer("Удалил.")
    await _show_flex(callback, session)


@router.callback_query(ManageCB.filter((F.section == "curve") & (F.action == "del")))
async def delete_curve(
    callback: CallbackQuery,
    callback_data: ManageCB,
    session: AsyncSession,
) -> None:
    try:
        await catalog.delete_curve(session, callback_data.item_id)
    except InUseError:
        await callback.answer(
            "Нельзя удалить: загиб уже используется.", show_alert=True
        )
        return
    await callback.answer("Удалил.")
    await _show_curves(callback, session)


@router.callback_query(ManageCB.filter((F.section == "grip") & (F.action == "del")))
async def delete_grip(
    callback: CallbackQuery,
    callback_data: ManageCB,
    session: AsyncSession,
) -> None:
    try:
        await catalog.delete_grip(session, callback_data.item_id)
    except InUseError:
        await callback.answer("Нельзя удалить: хват уже используется.", show_alert=True)
        return
    await callback.answer("Удалил.")
    await _show_grips(callback, session)


async def _show_sellers(callback: CallbackQuery, session: AsyncSession) -> None:
    items = await sellers_repo.list_sellers(session)
    message = _callback_message(callback)
    if message:
        await message.edit_text(
            "Продавцы — кому в кассу при продаже.",
            reply_markup=sellers_keyboard(items),
        )


@router.callback_query(ManageCB.filter((F.section == "seller") & (F.action == "list")))
async def list_sellers(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await _show_sellers(callback, session)


@router.callback_query(ManageCB.filter((F.section == "seller") & (F.action == "add")))
async def start_add_seller(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddSeller.name)
    await callback.answer()
    message = _callback_message(callback)
    if message:
        await message.answer("Имя продавца?")


@router.message(AddSeller.name, F.text, ~F.text.in_(MENU_TEXTS))
async def save_seller(message: Message, state: FSMContext, session: AsyncSession) -> None:
    name = _clean_name(message.text or "")
    if not name:
        await message.answer(NOT_TEXT)
        return
    try:
        await sellers_repo.create_seller(session, name)
    except DuplicateNameError:
        await message.answer("Такой продавец уже есть.")
        return
    await state.clear()
    items = await sellers_repo.list_sellers(session)
    await message.answer(f"Продавец «{name}» добавлен.", reply_markup=sellers_keyboard(items))


@router.callback_query(ManageCB.filter((F.section == "seller") & (F.action == "del")))
async def delete_seller(
    callback: CallbackQuery,
    callback_data: ManageCB,
    session: AsyncSession,
) -> None:
    try:
        await sellers_repo.delete_seller(session, callback_data.item_id)
    except InUseError:
        await callback.answer(
            "Нельзя удалить: есть продажи, переводы, изъятия или опт.",
            show_alert=True,
        )
        return
    await callback.answer("Удалил.")
    await _show_sellers(callback, session)
