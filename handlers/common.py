from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from config import settings
from keyboards.menu import main_menu

router = Router()


def _is_admin(message: Message) -> bool:
    user = message.from_user
    return bool(user and settings.is_admin(user.id))


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    admin = _is_admin(message)
    if admin:
        text = "Учёт клюшек. Продажа, поступление, наличие и финансы — кнопки внизу."
    else:
        text = "Остатки клюшек — кнопка «В наличии» внизу."
    await message.answer(text, reply_markup=main_menu(admin=admin))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменил.", reply_markup=main_menu(admin=_is_admin(message)))
