"""Методы прогноза цены.

Все методы работают с логарифмом цены: оценивают ожидаемое изменение (дрейф)
за горизонт, а неопределённость берут из исторической волатильности.
"""

import math
import statistics
from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence

from ..analytics.timeseries import Z80, Z95, log_returns

_NORMAL = statistics.NormalDist()
VOL_WINDOW = 250
RECENT_WINDOW = 60
SMA_WINDOW = 50

DriftFn = Callable[[Sequence[float], float], float]


def _recent_returns(closes: Sequence[float], window: int) -> List[float]:
    return log_returns(closes[-(window + 1):])


def drift_trend(closes: Sequence[float], steps: float) -> float:
    """Долгосрочный тренд: средняя доходность за год сохранится."""
    returns = _recent_returns(closes, VOL_WINDOW)
    return statistics.fmean(returns) * steps if returns else 0.0


def drift_none(closes: Sequence[float], steps: float) -> float:
    """Без тренда (случайное блуждание): лучшая оценка - текущая цена."""
    return 0.0


def drift_recent(closes: Sequence[float], steps: float) -> float:
    """Недавний импульс (последние ~3 месяца), ослабленный вдвое."""
    returns = _recent_returns(closes, RECENT_WINDOW)
    return 0.5 * statistics.fmean(returns) * steps if returns else 0.0


def drift_reversion(closes: Sequence[float], steps: float) -> float:
    """Возврат к средней: цена частично возвращается к 50-дневной средней."""
    window = closes[-SMA_WINDOW:]
    mean = sum(window) / len(window)
    if mean <= 0 or closes[-1] <= 0:
        return 0.0
    return 0.5 * math.log(mean / closes[-1]) * min(1.0, steps / SMA_WINDOW)


METHODS: Dict[str, DriftFn] = {
    "trend": drift_trend,
    "no_trend": drift_none,
    "recent_trend": drift_recent,
    "mean_reversion": drift_reversion,
}
METHOD_NAMES = {
    "trend": "долгосрочный тренд",
    "no_trend": "без тренда",
    "recent_trend": "недавний импульс",
    "mean_reversion": "возврат к средней",
}


def volatility(closes: Sequence[float]) -> float:
    """Волатильность за шаг (стандартное отклонение лог-доходностей)."""
    returns = _recent_returns(closes, VOL_WINDOW)
    return statistics.stdev(returns) if len(returns) > 1 else 0.0


@dataclass
class Prediction:
    median: float
    low_80: float
    high_80: float
    low_95: float
    high_95: float
    probability_up: float
    drift: float
    spread: float


def predict(
    closes: Sequence[float],
    steps: float,
    method: str = "trend",
    scale: float = 1.0,
    bias: float = 0.0,
) -> Prediction:
    """Прогноз через steps наблюдений.

    scale - множитель ширины интервалов, bias - поправка медианы в единицах
    неопределённости (оба - результат калибровки, по умолчанию без поправок).
    """
    if len(closes) < 3:
        raise ValueError("Для прогноза нужно хотя бы 3 значения")
    if method not in METHODS:
        raise ValueError(f"Неизвестный метод '{method}'")
    base_spread = volatility(closes) * math.sqrt(steps)
    drift = METHODS[method](closes, steps) + bias * base_spread
    spread = base_spread * scale
    last = closes[-1]
    prob_up = 0.5 if spread == 0 else _NORMAL.cdf(drift / spread)
    return Prediction(
        median=last * math.exp(drift),
        low_80=last * math.exp(drift - Z80 * spread),
        high_80=last * math.exp(drift + Z80 * spread),
        low_95=last * math.exp(drift - Z95 * spread),
        high_95=last * math.exp(drift + Z95 * spread),
        probability_up=prob_up,
        drift=drift,
        spread=spread,
    )
