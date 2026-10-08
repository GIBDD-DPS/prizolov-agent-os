# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Графики в PNG: история цены с коридором прогноза, остаток денег, помесячные потоки.

Цвета - из проверенной палитры: один синий для цены и прогноза (интервалы -
светлые ступени того же синего), синий/красный для поступлений и расходов.
Ось одна. На каждом графике есть подпись авторства, а в метаданных PNG - автор,
бренд и ID проекта.
"""

import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from .__about__ import (  # noqa: E402
    PROJECT_ID,
    SIGNATURE,
    __author__,
    __brand__,
    __copyright__,
    __title__,
)
from .analytics.cashflow import Transaction  # noqa: E402

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e6e5e1"
BLUE = "#2a78d6"  # серия 1
BLUE_DARK = "#1c5cab"  # медиана прогноза
BAND_80 = "#9ec5f4"  # синий, ступень 200
BAND_95 = "#cde2fb"  # синий, ступень 100
RED = "#e34948"  # расходы (противоположный полюс)
ZERO = "#8a8984"
FAN_POINTS = 30


def _figure(title: str, subtitle: str = "") -> Tuple[Any, Any]:
    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=120)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    # Фиксированная раскладка сверху вниз: заголовок, подзаголовок, легенда, график.
    fig.subplots_adjust(top=0.78, bottom=0.12, left=0.09, right=0.92)
    fig.text(0.02, 0.97, title, ha="left", va="top", fontsize=14, color=TEXT,
             fontweight="bold")
    if subtitle:
        fig.text(0.02, 0.905, subtitle, ha="left", va="top", fontsize=10, color=TEXT_SECONDARY)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=TEXT_SECONDARY, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    return fig, ax


def _save(fig: Any, path: Path, title: str) -> Path:
    fig.text(0.99, 0.01, SIGNATURE, ha="right", va="bottom", fontsize=7, color=TEXT_SECONDARY,
             alpha=0.8)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        path, facecolor=SURFACE, bbox_inches="tight",
        metadata={
            "Title": title,
            "Author": f"{__author__} / {__brand__}",
            "Copyright": __copyright__,
            "Software": __title__,
            "Description": f"{SIGNATURE} | {PROJECT_ID}",
        },
    )
    plt.close(fig)
    return path


def _money(value: float, _: Any = None) -> str:
    return f"{value:,.0f}".replace(",", " ")


def _date_axis(ax: Any) -> None:
    locator = mdates.AutoDateLocator(minticks=4, maxticks=8)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))


def _legend(ax: Any) -> None:
    # Легенда над областью графика, чтобы не закрывать данные и подписи.
    legend = ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), frameon=False, fontsize=9,
                       ncols=4, borderaxespad=0.0)
    for text in legend.get_texts():
        text.set_color(TEXT_SECONDARY)


def price_forecast_chart(
    path: Path, title: str, dates: Sequence[date], closes: Sequence[float],
    forecast: Dict[str, Any], unit: str = "",
) -> Path:
    """История цены и веер прогноза: медиана, интервалы 80% и 95%."""
    fig, ax = _figure(title, _forecast_subtitle(forecast, unit))
    ax.plot(dates, closes, color=BLUE, linewidth=2, label="История")

    last_date, last = dates[-1], closes[-1]
    horizon = forecast["horizon_days"]
    fan_dates, median, l80, h80, l95, h95 = [], [], [], [], [], []
    for i in range(FAN_POINTS + 1):
        share = i / FAN_POINTS
        fan_dates.append(last_date + timedelta(days=horizon * share))
        root = math.sqrt(share)
        log_median = math.log(last) + share * math.log(forecast["median"] / last)
        median.append(math.exp(log_median))
        for target, key in ((l80, "low_80"), (h80, "high_80"), (l95, "low_95"), (h95, "high_95")):
            spread = math.log(forecast[key] / forecast["median"])
            target.append(math.exp(log_median + root * spread))
    ax.fill_between(fan_dates, l95, h95, color=BAND_95, linewidth=0, label="Интервал 95%")
    ax.fill_between(fan_dates, l80, h80, color=BAND_80, linewidth=0, label="Интервал 80%")
    ax.plot(fan_dates, median, color=BLUE_DARK, linewidth=2, linestyle=(0, (4, 3)),
            label="Прогноз (медиана)")
    ax.plot([last_date], [last], "o", color=BLUE, markersize=8,
            markeredgecolor=SURFACE, markeredgewidth=2)
    ax.annotate(f"{last:,.2f}".replace(",", " "), (last_date, last), textcoords="offset points",
                xytext=(-8, 10), ha="right", fontsize=9, color=TEXT)
    ax.annotate(f"{forecast['median']:,.2f}".replace(",", " "), (fan_dates[-1], median[-1]),
                textcoords="offset points", xytext=(6, 0), va="center", fontsize=9, color=TEXT)
    _date_axis(ax)
    _legend(ax)
    return _save(fig, path, title)


def _forecast_subtitle(forecast: Dict[str, Any], unit: str) -> str:
    parts = [f"Прогноз на {forecast['horizon_days']} дн."]
    if forecast.get("method_name"):
        parts.append(f"метод: {forecast['method_name']}")
    reliability = forecast.get("reliability") or {}
    if reliability.get("backtest_forecasts"):
        parts.append(
            f"проверен на {reliability['backtest_forecasts']} прогнозах, в 80%-й интервал "
            f"попало {reliability['backtest_interval_80_pass_pct']}%"
        )
    if unit:
        parts.append(unit)
    return " · ".join(parts)


def daily_balance(
    transactions: Sequence[Transaction], opening_balance: float
) -> Tuple[List[date], List[float]]:
    start, end = transactions[0].date, transactions[-1].date
    flows: Dict[date, float] = {}
    for t in transactions:
        flows[t.date] = flows.get(t.date, 0.0) + t.amount
    days, balances, balance = [], [], opening_balance
    for i in range((end - start).days + 1):
        day = start + timedelta(days=i)
        balance += flows.get(day, 0.0)
        days.append(day)
        balances.append(balance)
    return days, balances


def cashflow_forecast_chart(
    path: Path, transactions: Sequence[Transaction], opening_balance: float,
    forecast: Dict[str, Any],
) -> Path:
    """Остаток денег по дням и прогноз с интервалами; линия нуля - граница кассового разрыва."""
    title = "Остаток денег и прогноз"
    subtitle = (
        f"Прогноз на {forecast['horizon_days']} дн. · вероятность уйти в минус "
        f"{forecast.get('probability_negative', 0) * 100:.0f}%"
    )
    fig, ax = _figure(title, subtitle)
    days, balances = daily_balance(transactions, opening_balance)
    ax.plot(days, balances, color=BLUE, linewidth=2, label="Остаток")

    last_date, last = days[-1], balances[-1]
    horizon = forecast["horizon_days"]
    expected = forecast["expected_balance"]
    fan = [last_date + timedelta(days=horizon * i / FAN_POINTS) for i in range(FAN_POINTS + 1)]
    mid = [last + (expected - last) * i / FAN_POINTS for i in range(FAN_POINTS + 1)]

    def band(low: str, high: str) -> Tuple[List[float], List[float]]:
        lows, highs = [], []
        for i, m in enumerate(mid):
            root = math.sqrt(i / FAN_POINTS)
            lows.append(m - root * (expected - forecast[low]))
            highs.append(m + root * (forecast[high] - expected))
        return lows, highs

    ax.fill_between(fan, *band("low_95", "high_95"), color=BAND_95, linewidth=0,
                    label="Интервал 95%")
    ax.fill_between(fan, *band("low_80", "high_80"), color=BAND_80, linewidth=0,
                    label="Интервал 80%")
    ax.plot(fan, mid, color=BLUE_DARK, linewidth=2, linestyle=(0, (4, 3)), label="Прогноз")
    ax.axhline(0, color=ZERO, linewidth=1)
    ax.annotate(_money(expected), (fan[-1], expected), textcoords="offset points",
                xytext=(6, 0), va="center", fontsize=9, color=TEXT)
    ax.yaxis.set_major_formatter(FuncFormatter(_money))
    _date_axis(ax)
    _legend(ax)
    return _save(fig, path, title)


def monthly_flows_chart(path: Path, monthly: Sequence[Dict[str, Any]]) -> Path:
    """Поступления (вверх) и расходы (вниз) по месяцам."""
    title = "Поступления и расходы по месяцам"
    fig, ax = _figure(title, "Поступления - вверх, расходы - вниз")
    months = [m["month"] for m in monthly]
    x = range(len(months))
    width = 0.6
    ax.bar(x, [m["inflow"] for m in monthly], width, color=BLUE, label="Поступления")
    ax.bar(x, [-m["outflow"] for m in monthly], width, color=RED, label="Расходы")
    ax.axhline(0, color=ZERO, linewidth=1)
    for i, m in enumerate(monthly):
        ax.annotate(f"итог {_money(m['net'])}", (i, max(m["inflow"], 0)),
                    textcoords="offset points", xytext=(0, 4), ha="center", fontsize=8,
                    color=TEXT_SECONDARY)
    ax.set_xticks(list(x), months)
    ax.margins(y=0.12)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _money(abs(v))))
    _legend(ax)
    return _save(fig, path, title)
