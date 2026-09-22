from aiogram.fsm.state import State, StatesGroup


class AddModel(StatesGroup):
    name = State()


class RenameModel(StatesGroup):
    name = State()


class AddColor(StatesGroup):
    name = State()


class AddFlex(StatesGroup):
    value = State()


class AddCurve(StatesGroup):
    name = State()


class AddGrip(StatesGroup):
    name = State()
