import asyncio
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ColorOption, CurveOption, FlexOption, GripOption, StickModel
from repositories import catalog
from utils.labels import color_title
from utils.money import format_money
from utils.sheet import (
    fetch_csv,
    iter_sheet_rows,
    normalize_flex,
    normalize_name,
    parse_color_cell,
    parse_sheet_money,
    parse_sheet_qty,
)


@dataclass(frozen=True)
class SheetBatch:
    model_id: int
    color_id: int
    flex_id: int
    curve_id: int
    grip_id: int
    quantity: int
    purchase_price: Decimal
    label: str


@dataclass(frozen=True)
class SheetPreview:
    errors: list[str]
    batches: list[SheetBatch]


def _color_title(color: ColorOption) -> str:
    return color_title(color)


def _one_by_name(items: list, attr: str, raw: str, *, flex: bool = False) -> tuple[object | None, str | None]:
    needle = normalize_flex(raw) if flex else normalize_name(raw)
    matches = []
    for item in items:
        value = getattr(item, attr)
        key = normalize_flex(value) if flex else normalize_name(value)
        if key == needle:
            matches.append(item)
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        return None, f"нет в справочнике «{raw.strip()}»"
    return None, f"в справочнике несколько «{raw.strip()}»"


def _match_color(colors: list[ColorOption], raw: str | None) -> tuple[ColorOption | None, str | None]:
    if raw is None:
        classic = next((item for item in colors if item.is_default), None)
        if classic is None:
            return None, "нет классики у модели"
        return classic, None
    needle = normalize_name(raw)
    matches = [item for item in colors if normalize_name(item.name) == needle]
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        return None, f"нет цвета «{raw.strip()}»"
    return None, f"цвет «{raw.strip()}» неоднозначен"


def _label(
    model: StickModel,
    color: ColorOption,
    flex: FlexOption,
    grip: GripOption,
    curve: CurveOption,
    quantity: int,
    price: Decimal,
) -> str:
    return (
        f"{model.name} / {_color_title(color)} · {flex.value} · "
        f"{grip.name} · {curve.name} — {quantity} шт · {format_money(price)}"
    )


async def parse_income_sheet(session: AsyncSession, url: str) -> SheetPreview:
    try:
        text = await asyncio.to_thread(fetch_csv, url)
    except ValueError as exc:
        return SheetPreview(errors=[str(exc)], batches=[])
    return await parse_income_csv(session, text)


async def parse_income_csv(session: AsyncSession, text: str) -> SheetPreview:
    _mapping, rows, header_error = iter_sheet_rows(text)
    if header_error:
        return SheetPreview(errors=[header_error], batches=[])
    if not rows:
        return SheetPreview(errors=["в таблице нет строк"], batches=[])

    models = await catalog.list_models(session)
    flexes = await catalog.list_flex(session)
    curves = await catalog.list_curves(session)
    grips = await catalog.list_grips(session)
    colors_by_model: dict[int, list[ColorOption]] = {}

    errors: list[str] = []
    batches: list[SheetBatch] = []
    for line_no, cells in rows:
        prefix = f"строка {line_no}"
        row_errors: list[str] = []
        model_raw = cells.get("model", "")
        flex_raw = cells.get("flex", "")
        curve_raw = cells.get("curve", "")
        grip_raw = cells.get("grip", "")
        qty_raw = cells.get("qty", "")
        price_raw = cells.get("price", "")
        color_raw = cells.get("color", "")

        if not model_raw:
            row_errors.append("нет модели")
        if not flex_raw:
            row_errors.append("нет flex")
        if not curve_raw:
            row_errors.append("нет загиба")
        if not grip_raw:
            row_errors.append("нет хвата")
        quantity = parse_sheet_qty(qty_raw)
        if quantity is None:
            row_errors.append("количество должно быть целым больше нуля")
        price = parse_sheet_money(price_raw)
        if price is None:
            row_errors.append("цена закупа должна быть целым числом")

        model = flex = curve = grip = None
        if model_raw:
            model, err = _one_by_name(models, "name", model_raw)
            if err:
                row_errors.append(f"модель: {err}")
        if flex_raw:
            flex, err = _one_by_name(flexes, "value", flex_raw, flex=True)
            if err:
                row_errors.append(f"flex: {err}")
        if curve_raw:
            curve, err = _one_by_name(curves, "name", curve_raw)
            if err:
                row_errors.append(f"загиб: {err}")
        if grip_raw:
            grip, err = _one_by_name(grips, "name", grip_raw)
            if err:
                row_errors.append(f"хват: {err}")

        splits: list[tuple[int, str | None]] = []
        if quantity is not None:
            splits, color_error = parse_color_cell(color_raw, quantity)
            if color_error:
                row_errors.append(color_error)

        if row_errors:
            errors.append(f"{prefix}: {'; '.join(row_errors)}")
            continue

        assert isinstance(model, StickModel)
        assert isinstance(flex, FlexOption)
        assert isinstance(curve, CurveOption)
        assert isinstance(grip, GripOption)
        assert quantity is not None
        assert price is not None

        if model.id not in colors_by_model:
            colors_by_model[model.id] = await catalog.list_colors(session, model.id)
        colors = colors_by_model[model.id]
        row_batches: list[SheetBatch] = []
        color_failed = False
        for split_qty, color_name in splits:
            color, color_error = _match_color(colors, color_name)
            if color_error or color is None:
                errors.append(f"{prefix}: {color_error or 'нет цвета'}")
                color_failed = True
                break
            row_batches.append(
                SheetBatch(
                    model_id=model.id,
                    color_id=color.id,
                    flex_id=flex.id,
                    curve_id=curve.id,
                    grip_id=grip.id,
                    quantity=split_qty,
                    purchase_price=price,
                    label=_label(model, color, flex, grip, curve, split_qty, price),
                )
            )
        if color_failed:
            continue
        batches.extend(row_batches)

    if errors:
        return SheetPreview(errors=errors, batches=[])
    return SheetPreview(errors=[], batches=batches)
