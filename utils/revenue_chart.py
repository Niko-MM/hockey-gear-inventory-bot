import math
import os
import tempfile
from datetime import date, timedelta
from io import BytesIO

from utils.dates import today

MONTH_SHORT = ("янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
CITY_COLORS = ("#007AFF", "#5E5CE6", "#FF9F0A", "#FF375F", "#64D2FF")
WHOLESALE_COLOR = "#30D158"
WHOLESALE_NAME = "Опт"
CITY_ORDER = ("Москва", "Челябинск", "Санкт-Петербург")


def _months_through_today(keys: set[tuple[int, int]], current: date) -> list[tuple[int, int]]:
    start = min(keys)
    end = (current.year, current.month)
    if start > end:
        start = end
    months: list[tuple[int, int]] = []
    year, month = start
    while (year, month) <= end:
        months.append((year, month))
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months


def _y_scale(peak: int) -> tuple[int, int]:
    if peak <= 0:
        return 40_000, 10_000
    rough = peak / 5
    power = 10 ** int(math.log10(rough))
    step = 10 * power
    for multiplier in (1, 2, 5, 10):
        if multiplier * power >= rough:
            step = multiplier * power
            break
    top = step * math.ceil(peak / step)
    if top == peak:
        top += step
    return int(top), int(step)


def _axis_money(value, _pos) -> str:
    number = int(value)
    if number == 0:
        return "0"
    if number >= 1_000_000:
        millions = number / 1_000_000
        if millions == int(millions):
            return f"{int(millions)} млн"
        text = f"{millions:.1f}".replace(".", ",").rstrip("0").rstrip(",")
        return f"{text} млн"
    return f"{number // 1000} тыс."


def _exact(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")


def _color(name: str, index: int) -> str:
    if name == WHOLESALE_NAME:
        return WHOLESALE_COLOR
    return CITY_COLORS[index % len(CITY_COLORS)]


def render_revenue_chart(series: dict[str, dict[tuple[int, int], int]]) -> bytes | None:
    kept = {
        name: months
        for name, months in series.items()
        if any(amount > 0 for amount in months.values())
    }
    if not kept:
        return None

    os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "mplconfig"))
    os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

    current = today()
    keys = {key for months in kept.values() for key in months}
    month_keys = _months_through_today(keys, current)
    open_key = (current.year, current.month)
    open_start = date(current.year, current.month, 1)
    closed_keys = [key for key in month_keys if key != open_key]
    names = [name for name in CITY_ORDER if name in kept]
    names.extend(sorted(name for name in kept if name not in names and name != WHOLESALE_NAME))
    if WHOLESALE_NAME in kept:
        names.append(WHOLESALE_NAME)
    amounts = [amount for months in kept.values() for amount in months.values()]
    top, step = _y_scale(max(amounts))

    plt.rcParams["font.family"] = "DejaVu Sans"
    fig, ax = plt.subplots(figsize=(12.8, 7.4), dpi=100)
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#ffffff")
    fig.subplots_adjust(left=0.10, right=0.97, top=0.86, bottom=0.16)

    for index, name in enumerate(names):
        color = _color(name, index)
        moments = [date(year, month, 1) for year, month in closed_keys]
        values = [kept[name].get(key, 0) for key in closed_keys]
        total = kept[name].get(open_key, 0)
        if current == open_start:
            moments.append(current)
            values.append(total)
        else:
            moments.append(open_start)
            values.append(total)
            moments.append(current)
            values.append(total)
        ax.plot(moments, values, color=color, linewidth=2.6, solid_capstyle="round", label=name)
        ax.scatter([current], [total], s=36, color=color, zorder=3)
        if total > 0:
            ax.annotate(
                _exact(total),
                xy=(current, total),
                xytext=(-8, 4),
                textcoords="offset points",
                va="bottom",
                ha="right",
                fontsize=12,
                color=color,
                zorder=4,
            )

    tick_moments = [date(year, month, 1) for year, month in closed_keys]
    if current != open_start:
        tick_moments.append(open_start)
    tick_moments.append(current)
    tick_labels = []
    for index, moment in enumerate(tick_moments):
        if moment == current and current != open_start:
            tick_labels.append(f"{moment.day} {MONTH_SHORT[moment.month - 1]}")
        else:
            name = MONTH_SHORT[moment.month - 1]
            if index == 0 or moment.month == 1:
                tick_labels.append(f"{name} {moment.year % 100:02d}")
            else:
                tick_labels.append(name)

    fig.text(0.10, 0.93, "Выручка по месяцам", fontsize=26, color="#1d1d1f")
    if current != open_start:
        ax.axvline(open_start, color="#d2d2d7", linewidth=1, zorder=0)
    ax.axvline(current, color="#d2d2d7", linewidth=1, zorder=0)
    left_pad = timedelta(days=15 if len(tick_moments) == 1 else 10)
    ax.set_xlim(tick_moments[0] - left_pad, current + timedelta(days=5))
    ax.set_xticks(tick_moments)
    ax.set_xticklabels(tick_labels)
    ax.set_ylim(0, top)
    ax.set_yticks(range(0, top + 1, step))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_axis_money))
    ax.tick_params(axis="x", labelsize=14, colors="#6e6e73", length=0, pad=8)
    ax.tick_params(axis="y", labelsize=13, colors="#86868b", length=0, pad=6)
    ax.grid(axis="y", color="#f2f2f7", linewidth=1)
    ax.grid(axis="x", visible=False)
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.legend(
        frameon=False,
        ncol=min(4, len(names)),
        loc="upper center",
        bbox_to_anchor=(0.5, -0.10),
        fontsize=13,
        labelcolor="#1d1d1f",
    )

    buffer = BytesIO()
    fig.savefig(buffer, format="png")
    plt.close(fig)
    return buffer.getvalue()
