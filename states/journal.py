from aiogram.fsm.state import State, StatesGroup


class JournalPeriod(StatesGroup):
    start = State()
    end = State()
