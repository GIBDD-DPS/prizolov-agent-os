"""Журнал прогнозов: запись, сверка с фактом и статистика точности."""

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..analytics.cashflow import Transaction
from ..memory import Store
from .backtest import MethodStats

SCHEMA = """
CREATE TABLE IF NOT EXISTS forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    bucket TEXT NOT NULL,
    method TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    base_date TEXT NOT NULL,
    target_date TEXT NOT NULL,
    base_value REAL NOT NULL,
    median REAL NOT NULL,
    raw_median REAL NOT NULL,
    base_spread REAL NOT NULL,
    low_80 REAL NOT NULL,
    high_80 REAL NOT NULL,
    low_95 REAL NOT NULL,
    high_95 REAL NOT NULL,
    probability_up REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    actual REAL,
    verified_at TEXT,
    error_pct REAL,
    z REAL,
    hit_80 INTEGER,
    hit_95 INTEGER,
    direction_ok INTEGER
);
CREATE INDEX IF NOT EXISTS idx_forecasts_status ON forecasts(status, target_date);
CREATE TABLE IF NOT EXISTS backtests (
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    bucket TEXT NOT NULL,
    method TEXT NOT NULL,
    n INTEGER NOT NULL,
    hits_80 INTEGER NOT NULL,
    hits_95 INTEGER NOT NULL,
    direction_n INTEGER NOT NULL,
    direction_hits INTEGER NOT NULL,
    abs_error_pct_sum REAL NOT NULL,
    z TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source, symbol, bucket, method)
);
CREATE TABLE IF NOT EXISTS calibration_resets (
    asset_class TEXT PRIMARY KEY,
    reset_at TEXT NOT NULL
);
"""

PENDING, VERIFIED, UNVERIFIABLE = "pending", "verified", "unverifiable"
# Если факт не удалось получить за столько дней после даты прогноза, сверку прекращаем.
GIVE_UP_DAYS = 30


@dataclass
class Forecast:
    id: int
    kind: str
    source: str
    symbol: str
    asset_class: str
    bucket: str
    method: str
    horizon_days: int
    base_date: date
    target_date: date
    base_value: float
    median: float
    raw_median: float
    base_spread: float
    low_80: float
    high_80: float
    probability_up: Optional[float]
    status: str
    actual: Optional[float]
    error_pct: Optional[float]
    hit_80: Optional[bool]
    direction_ok: Optional[bool]


@dataclass
class Accuracy:
    """Точность группы прогнозов."""

    n: int = 0
    pass_rate_80: Optional[float] = None
    pass_rate_95: Optional[float] = None
    direction_rate: Optional[float] = None
    direction_n: int = 0
    mean_abs_error_pct: Optional[float] = None

    def as_dict(self) -> Dict[str, Any]:
        def pct(value: Optional[float]) -> Optional[float]:
            return None if value is None else round(value * 100, 1)

        return {
            "forecasts": self.n,
            "interval_80_pass_pct": pct(self.pass_rate_80),
            "interval_95_pass_pct": pct(self.pass_rate_95),
            "direction_hit_pct": pct(self.direction_rate),
            "mean_abs_error_pct": (
                None if self.mean_abs_error_pct is None else round(self.mean_abs_error_pct, 2)
            ),
        }


class ForecastJournal:
    def __init__(self, store: Store) -> None:
        self.store = store
        store.add_schema(SCHEMA)

    # --- Запись --------------------------------------------------------------

    def record(
        self,
        *,
        kind: str,
        source: str,
        symbol: str,
        asset_class: str,
        bucket: str,
        method: str,
        horizon_days: int,
        base_date: date,
        base_value: float,
        median: float,
        raw_median: float,
        base_spread: float,
        low_80: float,
        high_80: float,
        low_95: float,
        high_95: float,
        probability_up: Optional[float],
    ) -> int:
        target = base_date + timedelta(days=horizon_days)
        return self.store.execute(
            "INSERT INTO forecasts (created_at, kind, source, symbol, asset_class, bucket, "
            "method, horizon_days, base_date, target_date, base_value, median, raw_median, "
            "base_spread, low_80, high_80, low_95, high_95, probability_up) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_now(), kind, source, symbol, asset_class, bucket, method, horizon_days,
             base_date.isoformat(), target.isoformat(), base_value, median, raw_median,
             base_spread, low_80, high_80, low_95, high_95, probability_up),
        ).lastrowid

    def save_backtest(
        self, source: str, symbol: str, asset_class: str, bucket: str,
        stats: Dict[str, MethodStats],
    ) -> None:
        """Сохраняет последнюю проверку на истории (заменяет прежнюю по этому активу)."""
        for s in stats.values():
            if not s.n:
                continue
            self.store.execute(
                "INSERT OR REPLACE INTO backtests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (source, symbol, asset_class, bucket, s.method, s.n, s.hits_80, s.hits_95,
                 s.direction_n, s.direction_hits, s.abs_error_pct_sum,
                 json.dumps([round(v, 4) for v in s.z]), _now()),
            )

    # --- Сверка --------------------------------------------------------------

    def due(self, today: date, kind: Optional[str] = None) -> List[Forecast]:
        sql = "SELECT * FROM forecasts WHERE status = ? AND target_date <= ?"
        params: tuple = (PENDING, today.isoformat())
        if kind:
            sql += " AND kind = ?"
            params += (kind,)
        return [_forecast(r) for r in self.store.query(sql + " ORDER BY id", params)]

    def pending(self) -> List[Forecast]:
        rows = self.store.query("SELECT * FROM forecasts WHERE status = ? ORDER BY id", (PENDING,))
        return [_forecast(r) for r in rows]

    def mark_verified(self, forecast: Forecast, actual: float) -> Forecast:
        if forecast.kind == "cashflow":
            z = (actual - forecast.raw_median) / forecast.base_spread if forecast.base_spread else 0
            direction = None
        else:
            z = (
                math.log(actual / forecast.raw_median) / forecast.base_spread
                if forecast.base_spread and actual > 0 else 0.0
            )
            prob = forecast.probability_up
            direction = (
                None if prob is None or abs(prob - 0.5) < 1e-9 or actual == forecast.base_value
                else (prob > 0.5) == (actual > forecast.base_value)
            )
        median = forecast.median
        error_pct = (actual - median) / abs(median) * 100 if median else 0.0
        row = self.store.query(
            "SELECT low_95, high_95 FROM forecasts WHERE id = ?", (forecast.id,)
        )[0]
        self.store.execute(
            "UPDATE forecasts SET status = ?, actual = ?, verified_at = ?, error_pct = ?, z = ?, "
            "hit_80 = ?, hit_95 = ?, direction_ok = ? WHERE id = ?",
            (VERIFIED, actual, _now(), error_pct, z,
             forecast.low_80 <= actual <= forecast.high_80,
             row["low_95"] <= actual <= row["high_95"],
             direction, forecast.id),
        )
        return self.get(forecast.id)  # type: ignore[return-value]

    def mark_unverifiable(self, forecast_id: int) -> None:
        self.store.execute(
            "UPDATE forecasts SET status = ?, verified_at = ? WHERE id = ?",
            (UNVERIFIABLE, _now(), forecast_id),
        )

    def verify_cashflow(self, transactions: Sequence[Transaction]) -> List[Forecast]:
        """Сверяет прогнозы остатка по новой выписке, если она покрывает их период."""
        if not transactions:
            return []
        start, end = transactions[0].date, transactions[-1].date
        verified = []
        for forecast in self.due(end, kind="cashflow"):
            if not (start <= forecast.base_date and forecast.target_date <= end):
                continue
            flows = sum(
                t.amount for t in transactions
                if forecast.base_date < t.date <= forecast.target_date
            )
            verified.append(self.mark_verified(forecast, forecast.base_value + flows))
        return verified

    def get(self, forecast_id: int) -> Optional[Forecast]:
        rows = self.store.query("SELECT * FROM forecasts WHERE id = ?", (forecast_id,))
        return _forecast(rows[0]) if rows else None

    # --- Статистика ----------------------------------------------------------

    def live_z(self, asset_class: str, bucket: str, method: Optional[str] = None) -> List[float]:
        """Ошибки сверенных прогнозов (для калибровки), после последнего сброса."""
        sql = (
            "SELECT z FROM forecasts WHERE status = ? AND asset_class = ? AND bucket = ? "
            "AND created_at > ?"
        )
        params: tuple = (VERIFIED, asset_class, bucket, self._reset_at(asset_class))
        if method:
            sql += " AND method = ?"
            params += (method,)
        return [r["z"] for r in self.store.query(sql, params) if r["z"] is not None]

    def backtest_z(self, asset_class: str, bucket: str, method: str) -> List[float]:
        rows = self.store.query(
            "SELECT z FROM backtests WHERE asset_class = ? AND bucket = ? AND method = ? "
            "AND updated_at > ?",
            (asset_class, bucket, method, self._reset_at(asset_class)),
        )
        return [v for r in rows for v in json.loads(r["z"])]

    def live_accuracy(
        self, asset_class: Optional[str] = None, bucket: Optional[str] = None,
        method: Optional[str] = None,
    ) -> Accuracy:
        sql, params = "SELECT * FROM forecasts WHERE status = ?", [VERIFIED]
        for column, value in (("asset_class", asset_class), ("bucket", bucket), ("method", method)):
            if value is not None:
                sql += f" AND {column} = ?"
                params.append(value)
        rows = self.store.query(sql, tuple(params))
        return _accuracy(
            n=len(rows),
            hits_80=sum(bool(r["hit_80"]) for r in rows),
            hits_95=sum(bool(r["hit_95"]) for r in rows),
            direction=[bool(r["direction_ok"]) for r in rows if r["direction_ok"] is not None],
            abs_errors=[abs(r["error_pct"]) for r in rows],
        )

    def leaderboard(self) -> List[Dict[str, Any]]:
        """Соревнование методов: проверка на истории и реальные сверки по классам."""
        rows = self.store.query(
            "SELECT asset_class, bucket, method, SUM(n) AS n, SUM(hits_80) AS h80, "
            "SUM(hits_95) AS h95, SUM(direction_n) AS dn, SUM(direction_hits) AS dh, "
            "SUM(abs_error_pct_sum) AS err FROM backtests "
            "GROUP BY asset_class, bucket, method ORDER BY asset_class, bucket"
        )
        board = []
        for r in rows:
            backtest = _accuracy(
                n=r["n"], hits_80=r["h80"], hits_95=r["h95"],
                direction=[True] * r["dh"] + [False] * (r["dn"] - r["dh"]),
                abs_errors=None, abs_error_sum=r["err"],
            )
            live = self.live_accuracy(r["asset_class"], r["bucket"], r["method"])
            board.append({
                "asset_class": r["asset_class"],
                "bucket": r["bucket"],
                "method": r["method"],
                "backtest": backtest,
                "live": live,
            })
        return board

    def counts(self) -> Dict[str, int]:
        rows = self.store.query("SELECT status, COUNT(*) AS n FROM forecasts GROUP BY status")
        return {r["status"]: r["n"] for r in rows}

    def reset(self, asset_class: Optional[str] = None) -> None:
        """Сбрасывает накопленную калибровку (данные остаются в журнале)."""
        classes = [asset_class] if asset_class else [
            r["asset_class"] for r in self.store.query(
                "SELECT DISTINCT asset_class FROM forecasts UNION "
                "SELECT DISTINCT asset_class FROM backtests"
            )
        ]
        for name in classes:
            self.store.execute(
                "INSERT OR REPLACE INTO calibration_resets VALUES (?, ?)", (name, _now())
            )

    def _reset_at(self, asset_class: str) -> str:
        rows = self.store.query(
            "SELECT reset_at FROM calibration_resets WHERE asset_class = ?", (asset_class,)
        )
        return rows[0]["reset_at"] if rows else ""


def _accuracy(
    n: int,
    hits_80: int,
    hits_95: int,
    direction: Iterable[bool],
    abs_errors: Optional[Iterable[float]],
    abs_error_sum: Optional[float] = None,
) -> Accuracy:
    if not n:
        return Accuracy()
    direction = list(direction)
    total_error = abs_error_sum if abs_error_sum is not None else sum(abs_errors or [])
    return Accuracy(
        n=n,
        pass_rate_80=hits_80 / n,
        pass_rate_95=hits_95 / n,
        direction_rate=sum(direction) / len(direction) if direction else None,
        direction_n=len(direction),
        mean_abs_error_pct=total_error / n,
    )


def _forecast(row: Any) -> Forecast:
    return Forecast(
        id=row["id"], kind=row["kind"], source=row["source"], symbol=row["symbol"],
        asset_class=row["asset_class"], bucket=row["bucket"], method=row["method"],
        horizon_days=row["horizon_days"],
        base_date=date.fromisoformat(row["base_date"]),
        target_date=date.fromisoformat(row["target_date"]),
        base_value=row["base_value"], median=row["median"], raw_median=row["raw_median"],
        base_spread=row["base_spread"], low_80=row["low_80"], high_80=row["high_80"],
        probability_up=row["probability_up"], status=row["status"], actual=row["actual"],
        error_pct=row["error_pct"],
        hit_80=None if row["hit_80"] is None else bool(row["hit_80"]),
        direction_ok=None if row["direction_ok"] is None else bool(row["direction_ok"]),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")
