import csv
import io
import re
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

REQUIRED_HEADERS = {
    "модель": "model",
    "flex": "flex",
    "загиб": "curve",
    "хват": "grip",
    "количество": "qty",
    "цена закупа": "price",
}
OPTIONAL_HEADERS = {
    "цвет": "color",
}
SKIP_HEADERS = {"фирма", "бренд", "brand"}
COLOR_QTY_RE = re.compile(r"^(\d+)\s*(.+)$")
SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


def normalize_header(value: str) -> str:
    return " ".join(value.replace("\ufeff", "").strip().casefold().split())


def normalize_name(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def normalize_flex(value: str) -> str:
    text = value.strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        number = Decimal(text)
    except InvalidOperation:
        return normalize_name(value)
    if number == number.to_integral_value():
        return str(int(number))
    return format(number.normalize())


def parse_sheet_qty(value: str) -> int | None:
    text = value.strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if number <= 0 or number != number.to_integral_value():
        return None
    return int(number)


def parse_sheet_money(value: str) -> Decimal | None:
    text = (
        value.strip()
        .replace(" ", "")
        .replace("\u00a0", "")
        .replace("₽", "")
        .replace("руб.", "")
        .replace("руб", "")
        .replace(",", ".")
    )
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if number <= 0 or number != number.to_integral_value():
        return None
    return number.quantize(Decimal("1"))


def parse_color_cell(raw: str, total: int) -> tuple[list[tuple[int, str | None]], str | None]:
    text = raw.strip()
    if not text:
        return [(total, None)], None
    parts = [part.strip() for part in re.split(r"[,;]+", text) if part.strip()]
    parsed: list[tuple[int | None, str]] = []
    for part in parts:
        match = COLOR_QTY_RE.fullmatch(part)
        if match:
            qty = int(match.group(1))
            name = match.group(2).strip()
            if not name:
                return [], f"непонятный цвет «{part}»"
            if qty <= 0:
                return [], "количество цвета должно быть больше нуля"
            parsed.append((qty, name))
        else:
            parsed.append((None, part))
    names = [normalize_name(name) for _, name in parsed]
    if len(names) != len(set(names)):
        return [], "цвет указан дважды"
    numbered = [(qty, name) for qty, name in parsed if qty is not None]
    bare = [name for qty, name in parsed if qty is None]
    if numbered and bare:
        return [], "в цвете смешаны «белый» и «4 белый»"
    if len(bare) > 1:
        return [], "несколько цветов без количества"
    if len(bare) == 1:
        return [(total, bare[0])], None
    assigned = sum(qty for qty, _ in numbered)
    if assigned > total:
        return [], f"в цвете {assigned} шт, в строке {total}"
    result: list[tuple[int, str | None]] = [(qty, name) for qty, name in numbered]
    rest = total - assigned
    if rest:
        result.append((rest, None))
    if not result:
        return [], "непонятный цвет"
    return result, None


def csv_export_url(url: str) -> str:
    raw = url.strip()
    match = SHEET_ID_RE.search(raw)
    if match is None:
        raise ValueError("Это не ссылка на Google Таблицу.")
    sheet_id = match.group(1)
    parsed = urlparse(raw)
    query = parse_qs(parsed.query)
    gid = query.get("gid", [None])[0]
    if parsed.fragment:
        fragment = parse_qs(parsed.fragment)
        gid = fragment.get("gid", [gid])[0]
        if gid is None and parsed.fragment.startswith("gid="):
            gid = parsed.fragment.split("=", 1)[1]
    if gid is None:
        gid = "0"
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def fetch_csv(url: str, *, timeout: int = 20) -> str:
    export = csv_export_url(url)
    request = Request(export, headers={"User-Agent": "hockey-gear-inventory-bot/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except HTTPError as exc:
        raise ValueError("Таблица недоступна. Проверь доступ «по ссылке».") from exc
    except URLError as exc:
        raise ValueError("Не удалось скачать таблицу.") from exc
    text = payload.decode("utf-8-sig")
    start = text.lstrip()[:200].lower()
    if start.startswith("<!doctype") or start.startswith("<html") or "<html" in start:
        raise ValueError("Таблица закрыта. Открой доступ «все, у кого есть ссылка».")
    return text


def map_headers(header_row: list[str]) -> tuple[dict[str, int], str | None]:
    mapping: dict[str, int] = {}
    for index, raw in enumerate(header_row):
        name = normalize_header(raw)
        if not name or name in SKIP_HEADERS:
            continue
        key = REQUIRED_HEADERS.get(name) or OPTIONAL_HEADERS.get(name)
        if key is None:
            continue
        if key in mapping:
            return {}, f"столбец «{name}» повторён"
        mapping[key] = index
    missing = [title for title, key in REQUIRED_HEADERS.items() if key not in mapping]
    if missing:
        return {}, "нет столбцов: " + ", ".join(missing)
    return mapping, None


def iter_sheet_rows(text: str) -> tuple[dict[str, int] | None, list[tuple[int, dict[str, str]]], str | None]:
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return None, [], "таблица пустая"
    mapping, error = map_headers(header)
    if error or mapping is None:
        return None, [], error or "нет шапки"
    rows: list[tuple[int, dict[str, str]]] = []
    for offset, raw in enumerate(reader, start=2):
        if not raw or not any(cell.strip() for cell in raw):
            continue
        cells = {key: (raw[index].strip() if index < len(raw) else "") for key, index in mapping.items()}
        if not any(cells.get(key) for key in ("model", "flex", "curve", "grip", "qty", "price", "color")):
            continue
        rows.append((offset, cells))
    return mapping, rows, None
