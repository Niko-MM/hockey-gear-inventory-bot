from aiogram.fsm.state import State, StatesGroup


class WriteOffFlow(StatesGroup):
    quantity = State()
