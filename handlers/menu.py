from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from keyboards.callbacks import NavCB
from keyboards.menu import BTN_INCOME, BTN_SALE, BTN_SERVICE, BTN_STOCK
from keyboards.service import manage_menu, service_menu

router = Router()

SOON = "Этот раздел подключим на следующем шаге."


@router.message(F.text == BTN_SALE)
async def open_sale(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(SOON)


@router.message(F.text == BTN_INCOME)
async def open_income(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(SOON)


@router.message(F.text == BTN_STOCK)
async def open_stock(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(SOON)


@router.message(F.text == BTN_SERVICE)
async def open_service(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Сервис", reply_markup=service_menu())


@router.callback_query(NavCB.filter(F.to == "service"))
async def cb_service(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_text("Сервис", reply_markup=service_menu())


@router.callback_query(NavCB.filter(F.to == "manage"))
async def cb_manage(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "Управление — заготовки для конструктора поступления:\n"
            "модели, цвета, флекс, загиб, хват.",
            reply_markup=manage_menu(),
        )


@router.callback_query(NavCB.filter(F.to.in_({"accounting", "edits"})))
async def cb_soon(callback: CallbackQuery) -> None:
    await callback.answer(SOON, show_alert=True)


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()
