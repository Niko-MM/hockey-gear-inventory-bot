from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from keyboards.callbacks import NavCB
from keyboards.menu import BTN_SERVICE
from keyboards.service import manage_menu, service_menu

router = Router()


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
            "Справочник: модели, цвета, флекс, загиб, хват и продавцы.",
            reply_markup=manage_menu(),
        )


@router.callback_query(NavCB.filter(F.to == "edits"))
async def cb_soon(callback: CallbackQuery) -> None:
    await callback.answer("Журнал подключим следующим шагом.", show_alert=True)


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()
