from aiogram.fsm.state import State, StatesGroup


class Income(StatesGroup):
    quantity = State()
    price = State()
