# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Платёжный календарь: будущие платежи и прогноз остатка по дням.

Плановые платежи (аренда, зарплата, налоги, счета поставщиков, ожидаемые оплаты
клиентов) хранятся в базе. Прогноз складывается из них и «фона» - среднего
дневного потока по истории без статей с регулярными плановыми платежами (иначе
зарплата учлась бы дважды); разовые плановые суммы добавляются сверх фона.
Неопределённость фона даёт интервалы и вероятность уйти в минус на каждый день.
"""

import math
import statistics
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from .analytics.cashflow import Transaction
from .analytics.categories import categorize
from .analytics.timeseries import Z80
from .memory import Store

REPEATS = ("", "weekly", "monthly", "quarterly")
REPEAT_NAMES = {"": "разово", "weekly": "еженедельно", "monthly": "ежемесячно",
                "quarterly": "ежеквартально"}
MAX_HORIZON_DAYS = 366
_NORMAL = statistics.NormalDist()

SCHEMA = """
CREATE TABLE IF NOT EXISTS planned_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    amount REAL NOT NULL,
    due_date TEXT NOT NULL,
    repeat TEXT NOT NULL DEFAULT '',
    until TEXT,
    category TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


@dataclass
class PlannedPayment:
    id: int
    title: str
    amount: float  # поступление +, платёж -
    due_date: date
    repeat: str
    until: Optional[date]
    category: str

    def occurrences(self, start: date, end: date) -> List[date]:
        """Даты платежа в диапазоне [start, end]."""
        result, when, step = [], self.due_date, 0
        last = min(end, self.until) if self.until else end
        while when <= last and step < 1000:
            if when >= start:
                result.append(when)
            if not self.repeat:
                break
            step += 1
            when = _shift(self.due_date, self.repeat, step)
        return result

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "amount": self.amount,
            "due_date": self.due_date.isoformat(), "repeat": self.repeat,
            "repeat_name": REPEAT_NAMES[self.repeat],
            "until": self.until.isoformat() if self.until else None,
            "category": self.category,
        }


def _shift(start: date, repeat: str, step: int) -> date:
    if repeat == "weekly":
        return start + timedelta(weeks=step)
    months = step * (3 if repeat == "quarterly" else 1)
    year, month = divmod(start.month - 1 + months, 12)
    year, month = start.year + year, month + 1
    # 31-е число в коротком месяце - последний день месяца.
    return date(year, month, min(start.day, monthrange(year, month)[1]))


class PaymentCalendar:
    def __init__(self, store: Store) -> None:
        self.store = store
        store.add_schema(SCHEMA)

    def add(
        self, title: str, amount: float, due_date: date, repeat: str = "",
        until: Optional[date] = None, category: str = "",
    ) -> PlannedPayment:
        title = " ".join(title.split())
        if not title:
            raise ValueError("Укажите, что это за платёж")
        if not amount:
            raise ValueError("Сумма не может быть нулевой: поступление - плюс, платёж - минус")
        if repeat not in REPEATS:
            raise ValueError("Повтор: weekly (еженедельно), monthly (ежемесячно), "
                             "quarterly (ежеквартально) или пусто (разово)")
        if until and until < due_date:
            raise ValueError("Дата окончания раньше даты первого платежа")
        category = category or categorize(Transaction(due_date, amount, title))
        payment_id = self.store.execute(
            "INSERT INTO planned_payments (title, amount, due_date, repeat, until, category, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title, float(amount), due_date.isoformat(), repeat,
             until.isoformat() if until else None, category,
             datetime.now(timezone.utc).isoformat()),
        ).lastrowid
        return self.get(payment_id)  # type: ignore[return-value]

    def get(self, payment_id: int) -> Optional[PlannedPayment]:
        rows = self.store.query("SELECT * FROM planned_payments WHERE id = ?", (payment_id,))
        return _payment(rows[0]) if rows else None

    def list(self) -> List[PlannedPayment]:
        rows = self.store.query("SELECT * FROM planned_payments ORDER BY due_date, id")
        return [_payment(r) for r in rows]

    def remove(self, payment_id: int) -> bool:
        cursor = self.store.execute("DELETE FROM planned_payments WHERE id = ?", (payment_id,))
        return cursor.rowcount > 0


def _payment(row: Any) -> PlannedPayment:
    return PlannedPayment(
        id=row["id"], title=row["title"], amount=row["amount"],
        due_date=date.fromisoformat(row["due_date"]), repeat=row["repeat"],
        until=date.fromisoformat(row["until"]) if row["until"] else None,
        category=row["category"],
    )


def project(
    transactions: Sequence[Transaction],
    opening_balance: float,
    planned: Sequence[PlannedPayment],
    horizon_days: int,
    start: Optional[date] = None,
) -> Dict[str, Any]:
    """Прогноз остатка по дням с учётом плановых платежей.

    start - первый день прогноза (по умолчанию - день после последней операции).
    """
    if not transactions:
        raise ValueError("Нет операций для прогноза")
    if not 1 <= horizon_days <= MAX_HORIZON_DAYS:
        raise ValueError(f"Горизонт: от 1 до {MAX_HORIZON_DAYS} дней")
    first, last = transactions[0].date, transactions[-1].date
    closing = opening_balance + sum(t.amount for t in transactions)
    start = start or last + timedelta(days=1)
    end = start + timedelta(days=horizon_days - 1)

    # Фон: средний дневной поток без статей, по которым есть регулярные плановые платежи
    # (иначе, например, зарплата учлась бы дважды). Разовые плановые суммы - сверх фона.
    planned_categories = {p.category for p in planned if p.repeat}
    background = [t for t in transactions if categorize(t) not in planned_categories]
    days = (last - first).days + 1
    daily: Dict[date, float] = {}
    for t in background:
        daily[t.date] = daily.get(t.date, 0.0) + t.amount
    flows = [daily.get(first + timedelta(days=i), 0.0) for i in range(days)]
    mean_daily = statistics.fmean(flows)
    sd_daily = statistics.stdev(flows) if len(flows) > 1 else 0.0

    by_day: Dict[date, List[Dict[str, Any]]] = {}
    for payment in planned:
        for when in payment.occurrences(start, end):
            by_day.setdefault(when, []).append(
                {"id": payment.id, "title": payment.title, "amount": payment.amount}
            )

    rows, planned_total = [], 0.0
    gap: Optional[Dict[str, Any]] = None
    lowest: Optional[Dict[str, Any]] = None
    for offset in range(horizon_days):
        when = start + timedelta(days=offset)
        n = offset + 1
        items = by_day.get(when, [])
        planned_total += sum(i["amount"] for i in items)
        expected = closing + mean_daily * n + planned_total
        spread = sd_daily * math.sqrt(n)
        prob = _NORMAL.cdf(-expected / spread) if spread > 0 else float(expected < 0)
        row = {
            "date": when.isoformat(), "planned": items, "expected": round(expected, 2),
            "low_80": round(expected - Z80 * spread, 2),
            "high_80": round(expected + Z80 * spread, 2),
            "probability_negative": round(prob, 3),
        }
        rows.append(row)
        if lowest is None or expected < lowest["expected"]:
            lowest = row
        if gap is None and expected < 0:
            gap = row

    result: Dict[str, Any] = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "closing_balance": round(closing, 2),
        "background_daily": round(mean_daily, 2),
        "planned_in_period": round(planned_total, 2),
        "days": rows,
        "lowest": lowest,
        "gap": None,
        "risky_days": [r["date"] for r in rows if r["probability_negative"] >= 0.2],
    }
    if gap is not None:
        before = [
            {**item, "date": r["date"]} for r in rows if r["date"] <= gap["date"]
            for item in r["planned"] if item["amount"] < 0
        ]
        result["gap"] = {
            "date": gap["date"],
            "days_from_start": (date.fromisoformat(gap["date"]) - start).days + 1,
            "shortfall": round(-lowest["expected"], 2) if lowest else 0.0,
            # Крупнейшие плановые платежи до разрыва - что можно попробовать перенести.
            "movable": sorted(before, key=lambda i: i["amount"])[:5],
        }
    return result


def parse_repeat(text: str) -> str:
    """Повтор из русских слов: «ежемесячно» -> monthly."""
    value = text.strip().lower()
    aliases = {
        "": "", "разово": "", "once": "", "нет": "",
        "еженедельно": "weekly", "неделя": "weekly", "weekly": "weekly",
        "ежемесячно": "monthly", "месяц": "monthly", "monthly": "monthly",
        "ежеквартально": "quarterly", "квартал": "quarterly", "quarterly": "quarterly",
    }
    if value not in aliases:
        raise ValueError("Повтор: разово, еженедельно, ежемесячно или ежеквартально")
    return aliases[value]


__all__ = ["PaymentCalendar", "PlannedPayment", "parse_repeat", "project"]
