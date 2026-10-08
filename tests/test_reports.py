# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Тесты отчётов без участия модели."""

import argparse
import io
import math
import random
from datetime import date, timedelta

from rich.console import Console

from cli.main import run_report
from prizolov_os.__about__ import SIGNATURE
from prizolov_os.config import settings
from prizolov_os.forecasting import ForecastEngine, ForecastJournal
from prizolov_os.market import MarketDataError, PriceSeries
from prizolov_os.memory import Store
from prizolov_os.reports import guess_source, market_report, save_report, to_markdown


class StubMarket:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def history(self, source, symbol, days):
        self.calls.append((source, symbol, days))
        if self.fail:
            raise MarketDataError("Нет связи")
        rng = random.Random(4)
        prices = [7000.0]
        for _ in range(days):
            prices.append(prices[-1] * math.exp(rng.gauss(0.0005, 0.01)))
        dates = [date(2025, 10, 8) + timedelta(i) for i in range(len(prices))]
        return PriceSeries(source, symbol.upper(), "RUB", dates, prices, "руб. за грамм")


def test_guess_source():
    assert guess_source("gold") == "cbr" and guess_source("USD") == "cbr"
    assert guess_source("GC=F") == "yahoo"


def test_report_all_horizons_recorded(tmp_path):
    journal = ForecastJournal(Store())
    market = StubMarket()
    report = market_report(market, ForecastEngine(journal), "GOLD", horizons=[30, 1, 7, 15])
    assert market.calls == [("cbr", "GOLD", 365)]
    assert [r.horizon_days for r in report.rows] == [1, 7, 15, 30]
    assert journal.counts() == {"pending": 4}
    for row in report.rows:
        f = row.forecast
        assert f["low_95"] < f["low_80"] < f["median"] < f["high_80"] < f["high_95"]
        assert row.reliability["backtest_forecasts"] > 0

    path = save_report(report, tmp_path / "reports")
    text = path.read_text()
    assert "| 1 дн. |" in text and "| 30 дн. |" in text
    assert "не инвестиционная рекомендация" in text and SIGNATURE in text
    assert report.chart.exists() and f"]({report.chart.name})" in text
    assert to_markdown(report) == text


def run(tmp_path, monkeypatch, market, horizons="1,7,15,30"):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "db.sqlite"))
    monkeypatch.setattr(settings, "workspace_dir", str(tmp_path / "ws"))
    out = io.StringIO()
    args = argparse.Namespace(symbol="GOLD", source=None, horizons=horizons, history=365)
    code = run_report(Console(file=out, width=200, color_system=None), args, market=market)
    return code, out.getvalue()


def test_cli_report(tmp_path, monkeypatch):
    code, out = run(tmp_path, monkeypatch, StubMarket())
    assert code == 0
    assert "Отчёт: GOLD (cbr)" in out and "Прогнозы" in out
    assert "30 дн." in out and "проверен на" in out
    assert list((tmp_path / "ws" / "reports").glob("GOLD-*.md"))


def test_cli_report_errors(tmp_path, monkeypatch):
    code, out = run(tmp_path, monkeypatch, StubMarket(fail=True))
    assert code == 1 and "Не удалось получить котировки" in out
    code, out = run(tmp_path, monkeypatch, StubMarket(), horizons="1,abc")
    assert code == 1 and "--horizons" in out
    code, out = run(tmp_path, monkeypatch, StubMarket(), horizons="0,500")
    assert code == 1
