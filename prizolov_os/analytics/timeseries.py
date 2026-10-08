# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Анализ ценовых рядов: индикаторы и вероятностный прогноз.

Прогноз строится по модели геометрического броуновского движения: средняя
доходность и волатильность берутся из истории. Это статистическая оценка
диапазона, а не предсказание: рынок может выйти за любые границы.
"""

import math
import statistics
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

_NORMAL = statistics.NormalDist()
Z80 = _NORMAL.inv_cdf(0.90)
Z95 = _NORMAL.inv_cdf(0.975)


def sma(values: Sequence[float], period: int) -> Optional[float]:
    """Простая скользящая средняя по последним period значениям."""
    if period <= 0 or len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema(values: Sequence[float], period: int) -> Optional[float]:
    """Экспоненциальная скользящая средняя (последнее значение)."""
    if period <= 0 or len(values) < period:
        return None
    alpha = 2 / (period + 1)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = alpha * value + (1 - alpha) * result
    return result


def rsi(values: Sequence[float], period: int = 14) -> Optional[float]:
    """Индекс относительной силы по Уайлдеру (0-100)."""
    if len(values) <= period:
        return None
    changes = [b - a for a, b in zip(values, values[1:])]
    gains = [max(c, 0.0) for c in changes]
    losses = [max(-c, 0.0) for c in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def log_returns(values: Sequence[float]) -> List[float]:
    return [math.log(b / a) for a, b in zip(values, values[1:]) if a > 0 and b > 0]


def max_drawdown(values: Sequence[float]) -> float:
    """Максимальная просадка от пика, в долях (0.25 = -25%)."""
    peak, worst = -math.inf, 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst


def forecast(values: Sequence[float], steps: float) -> Dict[str, float]:
    """Медиана и интервалы цены через steps наблюдений (модель GBM)."""
    returns = log_returns(values)
    if len(returns) < 2:
        raise ValueError("Для прогноза нужно хотя бы 3 значения")
    mu = statistics.fmean(returns)
    sigma = statistics.stdev(returns)
    last = values[-1]
    drift = mu * steps
    spread = sigma * math.sqrt(steps)
    prob_up = 0.5 if spread == 0 else _NORMAL.cdf(drift / spread)
    return {
        "median": last * math.exp(drift),
        "low_80": last * math.exp(drift - Z80 * spread),
        "high_80": last * math.exp(drift + Z80 * spread),
        "low_95": last * math.exp(drift - Z95 * spread),
        "high_95": last * math.exp(drift + Z95 * spread),
        "probability_up": prob_up,
    }


def analyze_series(
    dates: Sequence[date], closes: Sequence[float], horizon_days: int
) -> Dict[str, Any]:
    """Сводка по ценовому ряду: изменение, индикаторы, риск и прогноз.

    horizon_days - календарные дни; переводятся в число наблюдений по
    фактической частоте ряда (у акций ~252 торговых дня в году, у крипты 365).
    """
    if len(closes) != len(dates):
        raise ValueError("Длины рядов дат и цен не совпадают")
    if len(closes) < 3:
        raise ValueError("Слишком мало данных для анализа (нужно хотя бы 3 значения)")

    span_days = max((dates[-1] - dates[0]).days, 1)
    per_day = (len(closes) - 1) / span_days
    steps = max(horizon_days * per_day, 1.0)
    returns = log_returns(closes)
    daily_vol = statistics.stdev(returns) if len(returns) > 1 else 0.0
    last = closes[-1]

    def rounded(value: Optional[float], digits: int = 4) -> Optional[float]:
        return None if value is None else round(value, digits)

    indicators = {
        "sma_20": rounded(sma(closes, 20)),
        "sma_50": rounded(sma(closes, 50)),
        "sma_200": rounded(sma(closes, 200)),
        "ema_20": rounded(ema(closes, 20)),
        "rsi_14": rounded(rsi(closes, 14), 1),
    }
    prediction = {key: rounded(value) for key, value in forecast(closes, steps).items()}
    prediction["probability_up"] = round(prediction["probability_up"] or 0.0, 3)

    return {
        "first_date": dates[0].isoformat(),
        "last_date": dates[-1].isoformat(),
        "observations": len(closes),
        "last_price": rounded(last),
        "change_pct": round((last / closes[0] - 1) * 100, 2),
        "min_price": rounded(min(closes)),
        "max_price": rounded(max(closes)),
        "indicators": indicators,
        "volatility_annual_pct": round(daily_vol * math.sqrt(per_day * 365) * 100, 2),
        "max_drawdown_pct": round(max_drawdown(closes) * 100, 2),
        "forecast": {"horizon_days": horizon_days, **prediction},
        "recent": [
            {"date": d.isoformat(), "close": rounded(c)}
            for d, c in list(zip(dates, closes))[-10:]
        ],
    }
