from aiogram.fsm.state import State, StatesGroup


class AddSeller(StatesGroup):
    name = State()


class TransferCash(StatesGroup):
    amount = State()
