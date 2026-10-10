# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Портфель инвестора: загрузка, оценка, риск, стресс-тест, T-Invest (без сети)."""

import argparse
import io
import math
import random
import zlib
from datetime import date, timedelta
from pathlib import Path

import pytest
from rich.console import Console

from prizolov_os.market import MarketDataError, PriceSeries
from prizolov_os.portfolio import (
    PortfolioError,
    Position,
    TInvestClient,
    analyze_portfolio,
    guess_source,
    load_portfolio,
    parse_portfolio_csv,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
START = {"SBER": 280.0, "LKOH": 7000.0, "GOLD": 10000.0, "BTC-USD": 60000.0, "AAPL": 200.0,
         "USD": 90.0}


class MultiMarket:
    """Цены по тикерам: Мосбиржа и ЦБ - в рублях, Yahoo - в долларах."""

    def __init__(self, missing=()):
        self.missing = set(missing)
        self.calls = []

    def history(self, source, symbol, days):
        self.calls.append((source, symbol))
        if symbol in self.missing or (source, symbol) in self.missing:
            raise MarketDataError(f"нет данных по {symbol}")
        rng = random.Random(zlib.crc32(symbol.encode()))
        prices = [START.get(symbol, 100.0)]
        for _ in range(days):
            prices.append(prices[-1] * math.exp(rng.gauss(0.0003, 0.015)))
        dates = [date(2025, 9, 1) + timedelta(i) for i in range(len(prices))]
        currency = "USD" if source == "yahoo" else "RUB"
        return PriceSeries(source, symbol, currency, dates, prices)


def test_guess_source():
    assert guess_source("SBER") == "moex" and guess_source("GOLD") == "cbr"
    assert guess_source("BTC-USD") == "yahoo" and guess_source("GC=F") == "yahoo"


def test_parse_csv_and_demo():
    positions = parse_portfolio_csv("ticker,quantity\nsber,10\nAAPL,0\n")
    assert positions == [Position("SBER", 10.0, "", None)]
    demo = load_portfolio(EXAMPLES / "demo_portfolio.csv")
    assert [p.symbol for p in demo] == ["SBER", "LKOH", "GOLD", "BTC-USD", "AAPL"]
    assert demo[0].source == "moex" and demo[0].avg_price == 270
    with pytest.raises(PortfolioError):
        parse_portfolio_csv("name,amount\nx,1\n")
    with pytest.raises(PortfolioError):
        parse_portfolio_csv("ticker,quantity\n")


def test_analysis_values_risk_and_stress():
    market = MultiMarket()
    result = analyze_portfolio(load_portfolio(EXAMPLES / "demo_portfolio.csv"), market)
    rows = {r["symbol"]: r for r in result["positions"]}
    usd_rate = market.history("cbr", "USD", 14).closes[-1]
    aapl = rows["AAPL"]
    assert aapl["currency"] == "USD"
    assert aapl["value_rub"] == pytest.approx(10 * aapl["price"] * usd_rate, rel=1e-6)
    assert sum(r["weight_pct"] for r in result["positions"]) == pytest.approx(100, abs=0.05)
    assert rows["SBER"]["profit_pct"] is not None and rows["GOLD"]["profit_pct"] is None
    assert rows["SBER"]["asset_class"] == "акции (Мосбиржа)"
    assert 1 <= rows["SBER"]["forecast"]["probability_up_pct"] <= 99
    risk = result["risk"]
    assert risk["volatility_annual_pct"] > 0 and risk["var95_1d_rub"] > 0
    assert risk["max_drawdown_pct"] <= 0
    scenarios = {s["scenario"]: s for s in result["stress"]}
    foreign = rows["AAPL"]["value_rub"] + rows["BTC-USD"]["value_rub"]
    assert scenarios["Рубль ослаб на 20% (валютные активы +20% в рублях)"][
        "change_rub"] == pytest.approx(foreign * 0.2, rel=1e-6)
    assert scenarios["Российские акции -20%"]["change_rub"] < 0
    assert result["errors"] == []


def test_fallback_to_yahoo_and_errors():
    market = MultiMarket(missing={("moex", "MSFT")})
    result = analyze_portfolio([Position("MSFT", 2), Position("XXXX", 1, "moex"),
                                Position("SBER", 1)], MultiMarket(
        missing={("moex", "MSFT"), "XXXX"}))
    assert {r["symbol"] for r in result["positions"]} == {"MSFT", "SBER"}
    assert next(r for r in result["positions"] if r["symbol"] == "MSFT")["source"] == "yahoo"
    assert result["errors"] and "XXXX" in result["errors"][0]
    with pytest.raises(PortfolioError):
        analyze_portfolio([Position("XXXX", 1, "moex")], MultiMarket(missing={"XXXX"}))
    with pytest.raises(PortfolioError):
        analyze_portfolio([], market)


def test_concentration_warning():
    result = analyze_portfolio([Position("SBER", 1000), Position("LKOH", 1)], MultiMarket())
    assert any("SBER" in w for w in result["warnings"])


def test_tinvest_client_reads_positions():
    calls = []

    def post(method, body):
        calls.append(method)
        if method == "UsersService/GetAccounts":
            return {"accounts": [{"id": "A1", "status": "ACCOUNT_STATUS_OPEN"}]}
        if method == "OperationsService/GetPortfolio":
            assert body == {"accountId": "A1", "currency": "RUB"}
            return {"positions": [
                {"figi": "F1", "instrumentType": "share", "ticker": "SBER",
                 "quantity": {"units": "10", "nano": 0},
                 "averagePositionPrice": {"currency": "rub", "units": "250", "nano": 500000000}},
                {"figi": "F2", "instrumentType": "etf", "quantity": {"units": "3", "nano": 0}},
                {"figi": "RUB", "instrumentType": "currency", "quantity": {"units": "5000"}},
            ]}
        if method == "InstrumentsService/GetInstrumentBy":
            return {"instrument": {"ticker": "TMOS"}}
        raise AssertionError(method)

    positions = TInvestClient("token", post=post).positions()
    assert positions == [Position("SBER", 10.0, "moex", 250.5), Position("TMOS", 3.0, "moex")]
    assert "InstrumentsService/GetInstrumentBy" in calls
    with pytest.raises(PortfolioError):
        TInvestClient("")


def test_cli_portfolio(monkeypatch):
    from cli.main import run_portfolio

    out = io.StringIO()
    args = argparse.Namespace(file=str(EXAMPLES / "demo_portfolio.csv"), tinvest=False, days=30)
    code = run_portfolio(Console(file=out, width=220, color_system=None), args,
                         market=MultiMarket())
    text = out.getvalue()
    assert code == 0 and "Портфель:" in text and "Стресс-тест" in text and "VaR 95%" in text
    args = argparse.Namespace(file=None, tinvest=False, days=30)
    assert run_portfolio(Console(file=io.StringIO()), args, market=MultiMarket()) == 1
