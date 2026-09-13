from aiogram.fsm.state import State, StatesGroup


class SaleFlow(StatesGroup):
    quantity = State()
    amount = State()
