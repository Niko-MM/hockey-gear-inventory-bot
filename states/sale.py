from aiogram.fsm.state import State, StatesGroup


class SaleFlow(StatesGroup):
    amount = State()
