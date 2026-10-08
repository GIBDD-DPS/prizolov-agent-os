# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Калибровка прогноза по накопленным ошибкам.

scale - во сколько раз расширить (или сузить) интервалы, чтобы в 80%-й интервал
попадало ~80% фактов. bias - систематический сдвиг медианы в единицах
неопределённости. Применяется автоматически, но в границах и только при
достаточной статистике.
"""

import statistics
from dataclasses import dataclass
from typing import Sequence

from ..analytics.timeseries import Z80

MIN_SAMPLES = 10
SCALE_BOUNDS = (0.5, 2.0)
BIAS_BOUND = 0.5


@dataclass
class Calibration:
    scale: float = 1.0
    bias: float = 0.0
    samples: int = 0
    applied: bool = False


def calibrate(z: Sequence[float]) -> Calibration:
    """Подбирает поправки по ошибкам z (факт минус медиана в единицах неопределённости)."""
    if len(z) < MIN_SAMPLES:
        return Calibration(samples=len(z))
    bias = max(-BIAS_BOUND, min(BIAS_BOUND, statistics.fmean(z)))
    centered = sorted(abs(v - bias) for v in z)
    quantile = centered[min(len(centered) - 1, int(0.8 * len(centered)))]
    scale = max(SCALE_BOUNDS[0], min(SCALE_BOUNDS[1], quantile / Z80)) if quantile else 1.0
    return Calibration(scale=round(scale, 3), bias=round(bias, 3), samples=len(z), applied=True)
