# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Прогнозы, которые учатся на своих ошибках.

Для каждого прогноза:
1. Все методы проверяются на истории актива; выбирается метод с наименьшей ошибкой
   (если накоплено достаточно реальных сверок - по ним).
2. По ошибкам на истории и реальным сверкам калибруются интервалы и сдвиг медианы.
3. В ответ добавляется надёжность: на скольких прогнозах проверено, какой процент
   попал в интервал, как часто угадано направление.
4. Прогноз записывается в журнал, чтобы потом сверить его с фактом.
"""

import math
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

from ..analytics.cashflow import Transaction
from ..analytics.timeseries import Z80, Z95
from .backtest import MethodStats, backtest, best_method, coverage
from .calibration import MIN_SAMPLES, calibrate
from .classify import ASSET_CLASSES, asset_class, horizon_bucket
from .journal import ForecastJournal
from .methods import METHOD_NAMES, METHODS, predict

# Реальные сверки важнее проверки на истории: учитываются с двойным весом.
LIVE_WEIGHT = 2
WEAK_DIRECTION = 0.55


class ForecastEngine:
    def __init__(self, journal: Optional[ForecastJournal] = None) -> None:
        self.journal = journal

    # --- Рынок ---------------------------------------------------------------

    def market_forecast(
        self,
        source: str,
        symbol: str,
        dates: Sequence[date],
        closes: Sequence[float],
        horizon_days: int,
        record: bool = True,
    ) -> Dict[str, Any]:
        """record=False - только посчитать (например, для графика), не записывая в журнал."""
        klass, bucket = asset_class(source, symbol), horizon_bucket(horizon_days)
        span = max((dates[-1] - dates[0]).days, 1)
        steps = max(horizon_days * (len(closes) - 1) / span, 1.0)

        stats = backtest(closes, steps)
        if self.journal and record:
            self.journal.save_backtest(source, symbol, klass, bucket, stats)
        method = self._choose_method(stats, klass, bucket)

        z = self._calibration_sample(stats[method], klass, bucket, method)
        calib = calibrate(z)
        raw = predict(closes, steps, method)
        final = predict(closes, steps, method, scale=calib.scale, bias=calib.bias)

        reliability = self._reliability(stats[method], z, calib, klass, bucket, method)
        forecast: Dict[str, Any] = {
            "horizon_days": horizon_days,
            "method": method,
            "method_name": METHOD_NAMES[method],
            "median": round(final.median, 4),
            "low_80": round(final.low_80, 4),
            "high_80": round(final.high_80, 4),
            "low_95": round(final.low_95, 4),
            "high_95": round(final.high_95, 4),
            "probability_up": round(final.probability_up, 3),
            "calibration": {
                "applied": calib.applied,
                "interval_scale": calib.scale,
                "median_shift": calib.bias,
                "samples": calib.samples,
                "min_samples": MIN_SAMPLES,
            },
            "reliability": reliability,
            "method_competition": _competition(stats),
        }
        if self.journal and record:
            forecast["forecast_id"] = self.journal.record(
                kind="market", source=source, symbol=symbol, asset_class=klass,
                bucket=bucket, method=method, horizon_days=horizon_days,
                base_date=dates[-1], base_value=closes[-1],
                median=final.median, raw_median=raw.median, base_spread=raw.spread,
                low_80=final.low_80, high_80=final.high_80,
                low_95=final.low_95, high_95=final.high_95,
                probability_up=final.probability_up,
            )
        return forecast

    def _choose_method(self, stats: Dict[str, MethodStats], klass: str, bucket: str) -> str:
        if self.journal:
            live = {
                m: self.journal.live_accuracy(klass, bucket, m) for m in METHODS
            }
            proven = {m: a for m, a in live.items() if a.n >= MIN_SAMPLES}
            if proven:
                return min(proven, key=lambda m: proven[m].mean_abs_error_pct or math.inf)
        return best_method(stats)

    def _calibration_sample(
        self, stats: MethodStats, klass: str, bucket: str, method: str
    ) -> List[float]:
        if not self.journal:
            return list(stats.z)
        # Проверки на истории по всем активам класса (включая только что сохранённую).
        history = self.journal.backtest_z(klass, bucket, method)
        live = self.journal.live_z(klass, bucket, method)
        return (history or list(stats.z)) + live * LIVE_WEIGHT

    def _reliability(
        self, stats: MethodStats, z: List[float], calib: Any,
        klass: str, bucket: str, method: str,
    ) -> Dict[str, Any]:
        def pct(value: Optional[float]) -> Optional[float]:
            return None if value is None else round(value * 100, 1)

        expected_80 = coverage(z, calib.scale, calib.bias, Z80) if calib.applied else None
        expected_95 = coverage(z, calib.scale, calib.bias, Z95) if calib.applied else None
        live = self.journal.live_accuracy(klass, bucket, method) if self.journal else None
        result: Dict[str, Any] = {
            "asset_class": ASSET_CLASSES.get(klass, klass),
            "horizon_bucket": bucket,
            "backtest_forecasts": stats.n,
            "backtest_interval_80_pass_pct": pct(stats.pass_rate_80),
            "backtest_direction_hit_pct": pct(stats.direction_rate),
            "backtest_mean_abs_error_pct": (
                None if stats.mean_abs_error_pct is None else round(stats.mean_abs_error_pct, 2)
            ),
            "expected_interval_80_success_pct": pct(expected_80) if expected_80 else 80.0,
            "expected_interval_95_success_pct": pct(expected_95) if expected_95 else 95.0,
            "verified_live": live.as_dict() if live else {"forecasts": 0},
        }
        result["summary"] = _summary(stats, result, calib)
        return result

    # --- Остаток денег -------------------------------------------------------

    def cashflow_forecast(
        self, analysis: Dict[str, Any], transactions: Sequence[Transaction], path: str,
        record: bool = True,
    ) -> Dict[str, Any]:
        """Калибрует прогноз остатка и записывает его; сверяет старые прогнозы.

        record=False - только откалибровать (для графика), без сверки и записи.
        """
        forecast = analysis["forecast"]
        if not self.journal:
            return analysis
        verified = self.journal.verify_cashflow(transactions) if record else []
        live_z = self.journal.live_z("cashflow", horizon_bucket(forecast["horizon_days"]))
        calib = calibrate(live_z)

        expected_raw = forecast["expected_balance"]
        spread = (forecast["high_80"] - expected_raw) / Z80 if Z80 else 0.0
        expected = expected_raw + calib.bias * spread
        scaled = spread * calib.scale
        forecast.update({
            "expected_balance": round(expected, 2),
            "low_80": round(expected - Z80 * scaled, 2),
            "high_80": round(expected + Z80 * scaled, 2),
            "low_95": round(expected - Z95 * scaled, 2),
            "high_95": round(expected + Z95 * scaled, 2),
            "calibration": {"applied": calib.applied, "interval_scale": calib.scale,
                            "median_shift": calib.bias, "samples": calib.samples},
        })
        live = self.journal.live_accuracy("cashflow")
        forecast["reliability"] = {
            "verified_live": live.as_dict(),
            "summary": (
                f"Сверено прогнозов остатка: {live.n}."
                + (f" В 80%-й интервал попало {live.pass_rate_80 * 100:.0f}%, средняя ошибка "
                   f"{live.mean_abs_error_pct:.1f}%." if live.n else
                   " Точность станет известна, когда загрузите выписку за прогнозный период.")
            ),
        }
        if verified:
            forecast["verified_now"] = [
                {"forecast_id": f.id, "target_date": f.target_date.isoformat(),
                 "forecast": round(f.median, 2), "actual": round(f.actual or 0, 2),
                 "error_pct": round(f.error_pct or 0, 1), "within_80": f.hit_80}
                for f in verified
            ]
        if not record:
            return analysis
        end = transactions[-1].date
        forecast["forecast_id"] = self.journal.record(
            kind="cashflow", source="csv", symbol=path, asset_class="cashflow",
            bucket=horizon_bucket(forecast["horizon_days"]), method="average_flow",
            horizon_days=forecast["horizon_days"], base_date=end,
            base_value=analysis["closing_balance"], median=expected, raw_median=expected_raw,
            base_spread=spread, low_80=forecast["low_80"], high_80=forecast["high_80"],
            low_95=forecast["low_95"], high_95=forecast["high_95"], probability_up=None,
        )
        return analysis


def _competition(stats: Dict[str, MethodStats]) -> List[Dict[str, Any]]:
    rows = []
    for s in sorted(stats.values(), key=lambda s: s.mae_log):
        if not s.n:
            continue
        rows.append({
            "method": METHOD_NAMES[s.method],
            "tested_forecasts": s.n,
            "interval_80_pass_pct": round((s.pass_rate_80 or 0) * 100, 1),
            "direction_hit_pct": (
                None if s.direction_rate is None else round(s.direction_rate * 100, 1)
            ),
            "mean_abs_error_pct": round(s.mean_abs_error_pct or 0, 2),
        })
    return rows


def _summary(stats: MethodStats, r: Dict[str, Any], calib: Any) -> str:
    if not stats.n:
        return (
            "Истории недостаточно, чтобы проверить точность прогноза: интервалы "
            "рассчитаны теоретически, надёжность неизвестна."
        )
    parts = [
        f"Метод «{METHOD_NAMES[stats.method]}» проверен на {stats.n} прогнозах по истории "
        f"этого актива: в 80%-й интервал попало {r['backtest_interval_80_pass_pct']}% фактов, "
        f"средняя ошибка медианы {r['backtest_mean_abs_error_pct']}%."
    ]
    if calib.applied:
        parts.append(
            f"После калибровки ожидаемая вероятность попадания в 80%-й интервал "
            f"~{r['expected_interval_80_success_pct']:.0f}%."
        )
    direction = stats.direction_rate
    if direction is not None:
        parts.append(f"Направление угадывалось в {direction * 100:.0f}% случаев.")
        if direction < WEAK_DIRECTION:
            parts.append("Это почти случайно: о росте или падении уверенно говорить нельзя.")
    live = r["verified_live"]
    if live.get("forecasts"):
        parts.append(
            f"Реально сверено прогнозов: {live['forecasts']}, в 80%-й интервал попало "
            f"{live['interval_80_pass_pct']}%."
        )
    return " ".join(parts)
