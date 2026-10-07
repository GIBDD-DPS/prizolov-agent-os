"""Анализ движения денег по выписке в CSV и прогноз остатка."""

import csv
import io
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from .timeseries import Z80, Z95

_NORMAL = statistics.NormalDist()

DATE_COLUMNS = {"date", "дата", "дата операции", "дата платежа"}
AMOUNT_COLUMNS = {"amount", "сумма", "сумма операции", "сумма платежа"}
DESCRIPTION_COLUMNS = {
    "description", "описание", "назначение", "назначение платежа",
    "комментарий", "category", "категория", "контрагент",
}
DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%Y/%m/%d")


@dataclass
class Transaction:
    date: date
    amount: float
    description: str = ""


def parse_date(value: str) -> date:
    value = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Не удалось распознать дату '{value}'")


def parse_amount(value: str) -> float:
    cleaned = value.strip().replace(" ", "").replace(" ", "").replace("₽", "")
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")  # 1,234.50
    cleaned = cleaned.replace(",", ".").replace("−", "-")
    try:
        return float(cleaned)
    except ValueError:
        raise ValueError(f"Не удалось распознать сумму '{value}'") from None


def parse_cashflow_csv(text: str) -> List[Transaction]:
    """Читает CSV с колонками дата, сумма[, описание].

    Разделитель (, ; или табуляция) определяется автоматически. Поступления -
    положительные суммы, расходы - отрицательные.
    """
    text = text.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        raise ValueError("Файл пуст")

    header = [cell.strip().lower() for cell in rows[0]]

    def find(names: set) -> int:
        return next((i for i, name in enumerate(header) if name in names), -1)

    date_col, amount_col, desc_col = (
        find(DATE_COLUMNS), find(AMOUNT_COLUMNS), find(DESCRIPTION_COLUMNS)
    )
    if date_col < 0 or amount_col < 0:
        raise ValueError(
            "Нужны колонки с датой и суммой (например 'дата' и 'сумма'). "
            f"Найдены: {', '.join(header)}"
        )

    transactions = []
    for line_no, row in enumerate(rows[1:], start=2):
        try:
            transactions.append(Transaction(
                date=parse_date(row[date_col]),
                amount=parse_amount(row[amount_col]),
                description=row[desc_col].strip() if 0 <= desc_col < len(row) else "",
            ))
        except (ValueError, IndexError) as e:
            raise ValueError(f"Строка {line_no}: {e}") from None
    if not transactions:
        raise ValueError("В файле нет операций")
    return sorted(transactions, key=lambda t: t.date)


def analyze_cashflow(
    transactions: List[Transaction], opening_balance: float, horizon_days: int
) -> Dict[str, Any]:
    """Итоги, помесячные потоки, крупные расходы и прогноз остатка."""
    if not transactions:
        raise ValueError("Нет операций для анализа")
    if horizon_days <= 0:
        raise ValueError("Горизонт прогноза должен быть положительным")

    start, end = transactions[0].date, transactions[-1].date
    inflow = sum(t.amount for t in transactions if t.amount > 0)
    outflow = -sum(t.amount for t in transactions if t.amount < 0)
    closing = opening_balance + inflow - outflow

    months: Dict[str, Dict[str, float]] = defaultdict(lambda: {"inflow": 0.0, "outflow": 0.0})
    daily: Dict[date, float] = defaultdict(float)
    expenses: Dict[str, float] = defaultdict(float)
    for t in transactions:
        bucket = months[t.date.strftime("%Y-%m")]
        bucket["inflow" if t.amount > 0 else "outflow"] += abs(t.amount)
        daily[t.date] += t.amount
        if t.amount < 0:
            expenses[t.description or "(без описания)"] += -t.amount

    # Дневные чистые потоки, включая дни без операций.
    days = (end - start).days + 1
    flows = [daily.get(start + timedelta(days=i), 0.0) for i in range(days)]
    mean_daily = statistics.fmean(flows)
    sd_daily = statistics.stdev(flows) if len(flows) > 1 else 0.0

    expected = closing + mean_daily * horizon_days
    spread = sd_daily * math.sqrt(horizon_days)
    if spread > 0:
        prob_negative = _NORMAL.cdf(-expected / spread)
    else:
        prob_negative = float(expected < 0)

    result: Dict[str, Any] = {
        "period": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "transactions": len(transactions),
        "opening_balance": round(opening_balance, 2),
        "total_inflow": round(inflow, 2),
        "total_outflow": round(outflow, 2),
        "net_flow": round(inflow - outflow, 2),
        "closing_balance": round(closing, 2),
        "average_daily_net": round(mean_daily, 2),
        "monthly": [
            {"month": m, "inflow": round(v["inflow"], 2), "outflow": round(v["outflow"], 2),
             "net": round(v["inflow"] - v["outflow"], 2)}
            for m, v in sorted(months.items())
        ],
        "top_expenses": [
            {"description": d, "total": round(v, 2)}
            for d, v in sorted(expenses.items(), key=lambda kv: -kv[1])[:5]
        ],
        "forecast": {
            "horizon_days": horizon_days,
            "date": (end + timedelta(days=horizon_days)).isoformat(),
            "expected_balance": round(expected, 2),
            "low_80": round(expected - Z80 * spread, 2),
            "high_80": round(expected + Z80 * spread, 2),
            "low_95": round(expected - Z95 * spread, 2),
            "high_95": round(expected + Z95 * spread, 2),
            "probability_negative": round(prob_negative, 3),
        },
    }
    if mean_daily < 0 < closing:
        result["forecast"]["days_until_zero_at_current_rate"] = int(closing / -mean_daily)
    return result
