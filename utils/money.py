from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def format_money(amount: Decimal | int | str) -> str:
    value = int(Decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    sign = "-" if value < 0 else ""
    grouped = f"{abs(value):,}".replace(",", " ")
    return f"{sign}{grouped} ₽"


def parse_money(text: str) -> Decimal | None:
    cleaned = text.strip().replace(" ", "").replace("\u00a0", "")
    if not cleaned.isdigit():
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if value <= 0:
        return None
    return value
