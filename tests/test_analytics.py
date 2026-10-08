# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Тесты финансовой аналитики."""

import math
from datetime import date, timedelta

import pytest

from prizolov_os.analytics import (
    analyze_cashflow,
    analyze_series,
    ema,
    forecast,
    max_drawdown,
    parse_cashflow_csv,
    rsi,
    sma,
)

CASHFLOW_CSV = (
    "дата;сумма;назначение\n"
    "01.09.2026;150 000,00;Оплата от клиента\n"
    "05.09.2026;-40000;Аренда\n"
    "15.09.2026;-60 000;Зарплата\n"
    "01.10.2026;120000;Оплата от клиента\n"
    "05.10.2026;-40000;Аренда\n"
)


class TestIndicators:
    def test_sma(self):
        assert sma([1, 2, 3, 4], 2) == 3.5
        assert sma([1, 2], 5) is None

    def test_ema_constant_series(self):
        assert ema([5.0] * 30, 10) == pytest.approx(5.0)

    def test_rsi_extremes(self):
        assert rsi(list(range(1, 30))) == 100.0
        assert rsi(list(range(30, 1, -1))) == pytest.approx(0.0)
        assert rsi([1, 2]) is None

    def test_max_drawdown(self):
        assert max_drawdown([100, 120, 90, 130, 117]) == pytest.approx(0.25)

    def test_forecast_interval_ordering(self):
        prices = [100 * (1 + 0.01 * math.sin(i)) for i in range(60)]
        result = forecast(prices, 20)
        assert result["low_95"] < result["low_80"] < result["median"]
        assert result["median"] < result["high_80"] < result["high_95"]
        assert 0 <= result["probability_up"] <= 1

    def test_forecast_needs_data(self):
        with pytest.raises(ValueError):
            forecast([100, 101], 5)


class TestAnalyzeSeries:
    def test_summary(self):
        dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(60)]
        closes = [100 + i + (i % 3) for i in range(60)]
        result = analyze_series(dates, closes, 30)
        assert result["observations"] == 60
        assert result["last_price"] == closes[-1]
        assert result["indicators"]["sma_20"] is not None
        assert result["indicators"]["sma_200"] is None
        assert result["forecast"]["horizon_days"] == 30
        assert result["forecast"]["median"] > closes[-1]
        assert len(result["recent"]) == 10

    def test_length_mismatch(self):
        with pytest.raises(ValueError):
            analyze_series([date(2026, 1, 1)], [1.0, 2.0], 5)


class TestCashflow:
    def test_parse_russian_csv(self):
        transactions = parse_cashflow_csv(CASHFLOW_CSV)
        assert len(transactions) == 5
        assert transactions[0].date == date(2026, 9, 1)
        assert transactions[0].amount == 150000.0
        assert transactions[2].description == "Зарплата"

    def test_parse_english_comma_csv(self):
        text = "Date,Amount,Description\n2026-01-02,100.5,a\n2026-01-01,-20,b\n"
        transactions = parse_cashflow_csv(text)
        assert [t.amount for t in transactions] == [-20.0, 100.5]

    def test_missing_columns(self):
        with pytest.raises(ValueError, match="Нужны колонки"):
            parse_cashflow_csv("x;y\n1;2\n")

    def test_bad_row_reports_line(self):
        with pytest.raises(ValueError, match="Строка 3"):
            parse_cashflow_csv("дата;сумма\n01.01.2026;10\nвчера;5\n")

    def test_analyze(self):
        result = analyze_cashflow(parse_cashflow_csv(CASHFLOW_CSV), 50000, 30)
        assert result["total_inflow"] == 270000
        assert result["total_outflow"] == 140000
        assert result["closing_balance"] == 180000
        assert [m["month"] for m in result["monthly"]] == ["2026-09", "2026-10"]
        assert result["top_expenses"][0] == {"description": "Аренда", "total": 80000}
        fc = result["forecast"]
        assert fc["date"] == "2026-11-04"
        assert fc["low_95"] < fc["low_80"] < fc["expected_balance"] < fc["high_80"]
        assert "days_until_zero_at_current_rate" not in fc

    def test_burn_rate(self):
        text = "дата;сумма\n01.01.2026;-1000\n11.01.2026;-1000\n"
        fc = analyze_cashflow(parse_cashflow_csv(text), 10000, 30)["forecast"]
        assert fc["days_until_zero_at_current_rate"] > 0
        assert fc["expected_balance"] < 8000
