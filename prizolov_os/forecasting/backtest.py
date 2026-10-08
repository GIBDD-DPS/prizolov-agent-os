# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Проверка методов на истории (walk-forward).

Берём момент в прошлом, делаем прогноз только по данным до него и сравниваем
с тем, что случилось через горизонт. Повторяем для многих моментов.
"""

import math
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from ..analytics.timeseries import Z80, Z95
from .methods import METHODS, Prediction, predict, volatility

MIN_TRAIN = 30
MAX_ORIGINS = 60


@dataclass
class MethodStats:
    """Итоги проверки одного метода.

    z - ошибки в единицах неопределённости (для калибровки),
    errors - лог-ошибки медианы (факт минус прогноз).
    """

    method: str
    n: int = 0
    hits_80: int = 0
    hits_95: int = 0
    direction_n: int = 0
    direction_hits: int = 0
    abs_error_pct_sum: float = 0.0
    z: List[float] = field(default_factory=list, repr=False)
    errors: List[float] = field(default_factory=list, repr=False)

    def add(self, prediction: Prediction, last: float, actual: float) -> None:
        error = math.log(actual / prediction.median)
        unit = prediction.spread
        z = error / unit if unit > 0 else 0.0
        self.n += 1
        self.hits_80 += prediction.low_80 <= actual <= prediction.high_80
        self.hits_95 += prediction.low_95 <= actual <= prediction.high_95
        self.abs_error_pct_sum += abs(actual / prediction.median - 1) * 100
        if abs(prediction.probability_up - 0.5) > 1e-9 and actual != last:
            self.direction_n += 1
            self.direction_hits += (prediction.probability_up > 0.5) == (actual > last)
        self.z.append(z)
        self.errors.append(error)

    @property
    def pass_rate_80(self) -> Optional[float]:
        return self.hits_80 / self.n if self.n else None

    @property
    def pass_rate_95(self) -> Optional[float]:
        return self.hits_95 / self.n if self.n else None

    @property
    def direction_rate(self) -> Optional[float]:
        return self.direction_hits / self.direction_n if self.direction_n else None

    @property
    def mean_abs_error_pct(self) -> Optional[float]:
        return self.abs_error_pct_sum / self.n if self.n else None

    @property
    def mae_log(self) -> float:
        return statistics.fmean(abs(e) for e in self.errors) if self.errors else math.inf


def backtest(
    closes: Sequence[float], steps: float, methods: Sequence[str] = tuple(METHODS)
) -> Dict[str, MethodStats]:
    """Проверяет методы на истории. Пустая статистика, если данных мало."""
    horizon = max(1, round(steps))
    results = {m: MethodStats(m) for m in methods}
    first, last_origin = MIN_TRAIN - 1, len(closes) - 1 - horizon
    if last_origin < first:
        return results
    count = last_origin - first + 1
    stride = max(1, math.ceil(count / MAX_ORIGINS))
    for origin in range(last_origin, first - 1, -stride):
        history = closes[: origin + 1]
        if volatility(history) == 0:
            continue
        actual, last = closes[origin + horizon], history[-1]
        for method in methods:
            results[method].add(predict(history, horizon, method), last, actual)
    return results


def best_method(stats: Dict[str, MethodStats]) -> str:
    """Метод с наименьшей ошибкой медианы; без данных - тренд."""
    tested = [s for s in stats.values() if s.n]
    if not tested:
        return "trend"
    return min(tested, key=lambda s: s.mae_log).method


def coverage(z: Sequence[float], scale: float, bias: float, width: float = Z80) -> float:
    """Доля ошибок, попавших бы в интервал после калибровки."""
    if not z:
        return 0.0
    return sum(abs(v - bias) <= width * scale for v in z) / len(z)


__all__ = ["MethodStats", "Z95", "backtest", "best_method", "coverage"]
