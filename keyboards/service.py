from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.models import ColorOption, CurveOption, FlexOption, GripOption, StickModel
from keyboards.callbacks import ManageCB, NavCB


def service_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Бухгалтерия", callback_data=NavCB(to="accounting").pack())
    builder.button(text="Управление", callback_data=NavCB(to="manage").pack())
    builder.button(text="Последние операции", callback_data=NavCB(to="edits").pack())
    builder.adjust(1)
    return builder.as_markup()


def manage_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Модели", callback_data=ManageCB(section="model", action="list").pack())
    builder.button(text="Флекс", callback_data=ManageCB(section="flex", action="list").pack())
    builder.button(text="Загиб", callback_data=ManageCB(section="curve", action="list").pack())
    builder.button(text="Хват", callback_data=ManageCB(section="grip", action="list").pack())
    builder.button(text="« Сервис", callback_data=NavCB(to="service").pack())
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def models_keyboard(models: list[StickModel]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for model in models:
        builder.row(
            InlineKeyboardButton(
                text=model.name,
                callback_data=ManageCB(
                    section="color",
                    action="list",
                    model_id=model.id,
                ).pack(),
            ),
            InlineKeyboardButton(
                text="Удалить",
                callback_data=ManageCB(section="model", action="del", item_id=model.id).pack(),
            ),
        )
    builder.row(
        InlineKeyboardButton(
            text="Добавить модель",
            callback_data=ManageCB(section="model", action="add").pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(text="« Управление", callback_data=NavCB(to="manage").pack())
    )
    return builder.as_markup()


def colors_keyboard(model_id: int, colors: list[ColorOption]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for color in colors:
        if color.is_default:
            builder.row(InlineKeyboardButton(text=f"{color.name} (классика)", callback_data="noop"))
            continue
        builder.row(
            InlineKeyboardButton(text=color.name, callback_data="noop"),
            InlineKeyboardButton(
                text="Удалить",
                callback_data=ManageCB(
                    section="color",
                    action="del",
                    item_id=color.id,
                    model_id=model_id,
                ).pack(),
            ),
        )
    builder.row(
        InlineKeyboardButton(
            text="Добавить цвет",
            callback_data=ManageCB(section="color", action="add", model_id=model_id).pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="« Модели",
            callback_data=ManageCB(section="model", action="list").pack(),
        )
    )
    return builder.as_markup()


def named_options_keyboard(
    section: str,
    items: Sequence[FlexOption | CurveOption | GripOption],
    label_attr: str,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in items:
        title = getattr(item, label_attr)
        builder.row(
            InlineKeyboardButton(text=title, callback_data="noop"),
            InlineKeyboardButton(
                text="Удалить",
                callback_data=ManageCB(section=section, action="del", item_id=item.id).pack(),
            ),
        )
    builder.row(
        InlineKeyboardButton(
            text="Добавить",
            callback_data=ManageCB(section=section, action="add").pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(text="« Управление", callback_data=NavCB(to="manage").pack())
    )
    return builder.as_markup()
