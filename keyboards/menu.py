from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_SALE = "Продажа"
BTN_INCOME = "Поступление"
BTN_STOCK = "Остатки"
BTN_SERVICE = "Сервис"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_SALE), KeyboardButton(text=BTN_INCOME)],
            [KeyboardButton(text=BTN_STOCK), KeyboardButton(text=BTN_SERVICE)],
        ],
        resize_keyboard=True,
    )
