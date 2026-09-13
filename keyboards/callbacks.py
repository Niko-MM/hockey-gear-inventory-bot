from aiogram.filters.callback_data import CallbackData


class NavCB(CallbackData, prefix="nav"):
    to: str


class ManageCB(CallbackData, prefix="mgr"):
    section: str
    action: str
    item_id: int = 0
    model_id: int = 0


class IncomeCB(CallbackData, prefix="inc"):
    action: str
    step: str = ""
    item_id: int = 0


class SaleCB(CallbackData, prefix="sal"):
    action: str
    step: str = ""
    item_id: int = 0
    extra_id: int = 0
