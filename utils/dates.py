from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    BUSINESS_TZ = ZoneInfo("Europe/Moscow")
except ZoneInfoNotFoundError:
    BUSINESS_TZ = timezone(timedelta(hours=3))

MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def today() -> date:
    return datetime.now(BUSINESS_TZ).date()


def format_input_date(value: date) -> str:
    return f"{value.day:02d}.{value.month:02d}.{value.year % 100:02d}"


def parse_date(text: str) -> date | None:
    parts = text.strip().split(".")
    if len(parts) != 3:
        return None
    day_raw, month_raw, year_raw = parts
    if len(year_raw) not in (2, 4):
        return None
    try:
        day = int(day_raw)
        month = int(month_raw)
        year = int(year_raw)
    except ValueError:
        return None
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def format_range(start: date, end: date) -> str:
    if start == end:
        return f"{start.day} {MONTHS[start.month - 1]} {start.year}"
    if start.month == end.month and start.year == end.year:
        return f"{start.day}–{end.day} {MONTHS[start.month - 1]} {end.year}"
    return f"{start.day:02d}.{start.month:02d}.{start.year} — {end.day:02d}.{end.month:02d}.{end.year}"


def period_utc_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    begin = datetime.combine(start, time.min, tzinfo=BUSINESS_TZ)
    finish = datetime.combine(end + timedelta(days=1), time.min, tzinfo=BUSINESS_TZ)
    return (
        begin.astimezone(timezone.utc).replace(tzinfo=None),
        finish.astimezone(timezone.utc).replace(tzinfo=None),
    )


def as_local(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(BUSINESS_TZ)
