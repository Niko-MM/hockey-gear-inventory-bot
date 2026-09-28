from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_SALE = "Продажа"
BTN_INCOME = "Поступление"
BTN_STOCK = "В наличии"
BTN_SERVICE = "Сервис"


def main_menu(*, admin: bool = True) -> ReplyKeyboardMarkup:
    if admin:
        keyboard = [
            [KeyboardButton(text=BTN_SALE), KeyboardButton(text=BTN_INCOME)],
            [KeyboardButton(text=BTN_STOCK), KeyboardButton(text=BTN_SERVICE)],
        ]
    else:
        keyboard = [[KeyboardButton(text=BTN_STOCK)]]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
