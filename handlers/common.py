from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from keyboards.menu import main_menu

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Бот учёта клюшек.\n"
        "Продажа, поступление и остатки — следующий этап.\n"
        "Сейчас можно заполнить детали в Сервис → Управление.",
        reply_markup=main_menu(),
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменил. Главное меню.", reply_markup=main_menu())
