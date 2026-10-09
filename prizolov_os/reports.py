# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Отчёты без участия модели: прогнозы на несколько горизонтов, таблица и график.

Считаются тем же кодом, что и у рыночного аналитика (выбор метода по точности на
истории, калибровка, надёжность). Бесплатно и без ключа Claude. Прогнозы
записываются в журнал, чтобы потом сверить их с фактом.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .__about__ import SIGNATURE
from .analytics import analyze_series
from .forecasting import ForecastEngine
from .market import CBR_CURRENCIES, CBR_METALS, MarketData, PriceSeries

DEFAULT_HORIZONS = (1, 7, 15, 30)
DISCLAIMER = (
    "Это статистическая оценка по истории цен, а не инвестиционная рекомендация. "
    "Рынок может выйти за любые границы."
)


@dataclass
class HorizonRow:
    horizon_days: int
    forecast: Dict[str, Any]

    @property
    def reliability(self) -> Dict[str, Any]:
        return self.forecast.get("reliability") or {}


@dataclass
class MarketReport:
    source: str
    symbol: str
    currency: str
    unit: str
    created: datetime
    summary: Dict[str, Any]
    rows: List[HorizonRow] = field(default_factory=list)
    chart: Optional[Path] = None
    dates: Sequence[date] = field(default_factory=list, repr=False)
    closes: Sequence[float] = field(default_factory=list, repr=False)

    @property
    def last_price(self) -> float:
        return self.summary["last_price"]

    @property
    def title(self) -> str:
        return f"{self.symbol} ({self.source})"


def guess_source(symbol: str) -> str:
    """Источник по тикеру: коды ЦБ (USD, GOLD...) - cbr, иначе yahoo."""
    code = symbol.upper()
    if code in CBR_METALS or code in CBR_CURRENCIES:
        return "cbr"
    return "yahoo"


def market_report(
    market: MarketData,
    engine: ForecastEngine,
    symbol: str,
    source: Optional[str] = None,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    history_days: int = 365,
    series: Optional[PriceSeries] = None,
) -> MarketReport:
    """Отчёт по активу. series - готовый ряд (например, из файла) вместо загрузки."""
    if series is None:
        series = market.history(source or guess_source(symbol), symbol, history_days)
    summary = analyze_series(series.dates, series.closes, max(horizons))
    summary.pop("forecast", None)
    report = MarketReport(
        source=series.source, symbol=series.symbol, currency=series.currency,
        unit=series.unit, created=datetime.now(), summary=summary,
        dates=series.dates, closes=series.closes,
    )
    for horizon in sorted(set(horizons)):
        forecast = engine.market_forecast(
            series.source, series.symbol, series.dates, series.closes, horizon
        )
        report.rows.append(HorizonRow(horizon, forecast))
    return report


def load_price_file(path: Path) -> PriceSeries:
    """Ряд цен из CSV или Excel: колонки даты (date/дата) и цены (close/цена/курс)."""
    from .tools.builtin import Workspace
    from .tools.finance import parse_price_csv

    path = Path(path)
    dates, closes = parse_price_csv(Workspace(path.parent).read_table(path.name))
    if len(closes) < 30:
        raise ValueError(f"В файле {len(closes)} цен; для прогноза нужно хотя бы 30")
    return PriceSeries("csv", path.stem, "", dates, closes)


def save_report(report: MarketReport, directory: Path) -> Path:
    """Сохраняет отчёт в Markdown и график PNG (самый длинный горизонт)."""
    from . import charts

    directory.mkdir(parents=True, exist_ok=True)
    slug = "".join(c if c.isalnum() else "_" for c in report.symbol).strip("_") or "report"
    stamp = report.created.strftime("%Y%m%d-%H%M%S")
    longest = report.rows[-1].forecast
    report.chart = charts.price_forecast_chart(
        directory / f"{slug}-{stamp}.png", report.title, report.dates, report.closes,
        longest, report.unit,
    )
    path = directory / f"{slug}-{stamp}.md"
    path.write_text(to_markdown(report), encoding="utf-8")
    return path


def _pct(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:.0f}%"


def _num(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ")


def table_rows(report: MarketReport) -> List[List[str]]:
    """Строки таблицы прогнозов (для CLI, Markdown и Telegram)."""
    rows = []
    for row in report.rows:
        f, r = row.forecast, row.reliability
        change = (f["median"] / report.last_price - 1) * 100
        rows.append([
            f"{row.horizon_days} дн.",
            _num(f["median"]),
            f"{change:+.2f}%",
            f"{_num(f['low_80'])} – {_num(f['high_80'])}",
            f"{_num(f['low_95'])} – {_num(f['high_95'])}",
            f"{f['probability_up'] * 100:.0f}%",
            f["method_name"],
            str(r.get("backtest_forecasts", 0)),
            _pct(r.get("backtest_interval_80_pass_pct")),
            _pct(r.get("backtest_direction_hit_pct")),
        ])
    return rows


TABLE_HEADER = [
    "Горизонт", "Медиана", "Изменение", "Интервал 80%", "Интервал 95%", "Рост",
    "Метод", "Проверено", "В 80%", "Направление",
]


def to_markdown(report: MarketReport) -> str:
    s = report.summary
    ind = s.get("indicators", {})
    if report.unit:
        unit = f" ({report.unit})"
    else:
        unit = f", {report.currency}" if report.currency else ""
    lines = [
        f"# Отчёт: {report.title}",
        "",
        f"Сформирован {report.created:%d.%m.%Y %H:%M}. Данные: {s['first_date']} – "
        f"{s['last_date']}, {s['observations']} наблюдений{unit}.",
        "",
        "## Текущее состояние",
        "",
        f"- Последняя цена: **{_num(report.last_price)}** ({s['last_date']})",
        f"- Изменение за период: {s['change_pct']:+.2f}%",
        f"- RSI(14): {ind.get('rsi_14', '—')}; SMA20: {ind.get('sma_20', '—')}; "
        f"SMA50: {ind.get('sma_50', '—')}",
        f"- Годовая волатильность: {s['volatility_annual_pct']}%; "
        f"максимальная просадка: {s['max_drawdown_pct']}%",
        "",
        "## Прогнозы",
        "",
        "| " + " | ".join(TABLE_HEADER) + " |",
        "|" + "---|" * len(TABLE_HEADER),
    ]
    lines += ["| " + " | ".join(cells) + " |" for cells in table_rows(report)]
    lines += [
        "",
        "«Проверено» - на скольких прогнозах по истории проверен метод; «В 80%» - какая "
        "доля фактов попала в 80%-й интервал; «Направление» - как часто угадывался рост "
        "или падение (около 50% - не лучше случайного).",
        "",
        "## Надёжность по горизонтам",
        "",
    ]
    lines += [f"- **{row.horizon_days} дн.:** {row.reliability.get('summary', '')}"
              for row in report.rows]
    if report.chart:
        lines += ["", f"![График]({report.chart.name})"]
    lines += ["", f"_{DISCLAIMER}_", "", "---", f"_{SIGNATURE}_", ""]
    return "\n".join(lines)
