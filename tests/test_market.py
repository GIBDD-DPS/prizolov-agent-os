# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Тесты загрузки котировок и финансовых инструментов (без сети)."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from prizolov_os.llm import ToolCall
from prizolov_os.market import MarketData, MarketDataError
from prizolov_os.tools import ToolRegistry, Workspace, cashflow_tool, market_tools

TODAY = date(2026, 10, 7)


def yahoo_payload(n=30):
    start = datetime(2026, 9, 1, 14, tzinfo=timezone.utc)
    stamps = [int((start + timedelta(days=i)).timestamp()) for i in range(n)]
    closes = [2500.0 + i for i in range(n)]
    closes[3] = None  # Yahoo иногда возвращает пропуски
    return json.dumps({"chart": {"result": [{
        "meta": {"currency": "USD", "symbol": "GC=F"},
        "timestamp": stamps,
        "indicators": {"quote": [{"close": closes}]},
    }], "error": None}}).encode()


def moex_page(rows, total):
    return json.dumps({
        "history": {"columns": ["TRADEDATE", "CLOSE"], "data": rows},
        "history.cursor": {"columns": ["INDEX", "TOTAL", "PAGESIZE"], "data": [[0, total, 100]]},
    }).encode()


CBR_FX = """<?xml version="1.0" encoding="windows-1251"?>
<ValCurs ID="R01820" name="Foreign Currency Market Dynamic">
<Record Date="01.10.2026" Id="R01820"><Nominal>100</Nominal><Value>62,5000</Value></Record>
<Record Date="02.10.2026" Id="R01820"><Nominal>100</Nominal><Value>63,0000</Value></Record>
<Record Date="03.10.2026" Id="R01820"><Nominal>100</Nominal><Value>63,5000</Value></Record>
</ValCurs>""".encode("cp1251")

CBR_METALS_XML = b"""<?xml version="1.0" encoding="windows-1251"?>
<Metall FromDate="20261001" ToDate="20261006" name="Precious metals quotations">
<Record Date="01.10.2026" Code="1"><Buy>8000,10</Buy><Sell>8000,10</Sell></Record>
<Record Date="01.10.2026" Code="2"><Buy>95,50</Buy><Sell>95,50</Sell></Record>
<Record Date="02.10.2026" Code="1"><Buy>8050,20</Buy><Sell>8050,20</Sell></Record>
<Record Date="03.10.2026" Code="1"><Buy>8100,30</Buy><Sell>8100,30</Sell></Record>
</Metall>"""


class FakeFetch:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        return self.responses.pop(0)


def market(*responses):
    fetch = FakeFetch(*responses)
    return MarketData(fetch=fetch, today=lambda: TODAY), fetch


class TestYahoo:
    def test_parses_and_skips_missing(self):
        data, fetch = market(yahoo_payload())
        series = data.history("yahoo", "GC=F", 60)
        assert series.currency == "USD"
        assert len(series.closes) == 29
        assert series.dates[0] == date(2026, 9, 1)
        assert "GC%3DF" in fetch.urls[0]
        assert "interval=1d" in fetch.urls[0]

    def test_error(self):
        payload = json.dumps(
            {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data"}}}
        ).encode()
        data, _ = market(payload)
        with pytest.raises(MarketDataError, match="No data"):
            data.history("yahoo", "NOPE", 30)


class TestMoex:
    def test_paginates(self):
        page1 = [[f"2026-08-{d:02d}", 300.0 + d] for d in range(1, 31)]
        page2 = [["2026-09-01", 340.0], ["2026-09-02", None]]
        data, fetch = market(moex_page(page1, 32), moex_page(page2, 32))
        series = data.history("moex", "sber", 90)
        assert series.symbol == "SBER"
        assert series.currency == "RUB"
        assert len(series.closes) == 31
        assert "/boards/TQBR/securities/SBER.json" in fetch.urls[0]
        assert "start=30" in fetch.urls[1]

    def test_falls_back_to_etf_board(self):
        rows = [[f"2026-09-{d:02d}", 10.0 + d] for d in range(1, 6)]
        data, fetch = market(moex_page([], 0), moex_page(rows, 5))
        series = data.history("moex", "LQDT", 30)
        assert len(series.closes) == 5
        assert "/boards/TQTF/" in fetch.urls[1]


class TestCbr:
    def test_currency_divides_by_nominal(self):
        data, fetch = market(CBR_FX)
        series = data.history("cbr", "jpy", 30)
        assert series.closes == [0.625, 0.63, 0.635]
        assert "VAL_NM_RQ=R01820" in fetch.urls[0]
        assert "date_req2=07/10/2026" in fetch.urls[0]

    def test_metal_filters_by_code(self):
        data, _ = market(CBR_METALS_XML)
        series = data.history("cbr", "GOLD", 30)
        assert series.closes == [8000.10, 8050.20, 8100.30]
        assert series.unit == "руб. за грамм"

    def test_unknown_code(self):
        data, _ = market()
        with pytest.raises(MarketDataError, match="неизвестный код"):
            data.history("cbr", "XXX", 30)


class TestValidation:
    def test_unknown_source(self):
        with pytest.raises(MarketDataError, match="Неизвестный источник"):
            market()[0].history("bloomberg", "AAPL", 30)

    def test_too_little_data(self):
        data, _ = market(moex_page([["2026-10-01", 1.0]], 1), moex_page([], 0))
        with pytest.raises(MarketDataError, match="Слишком мало данных"):
            data.history("moex", "SBER", 30)


class TestFinanceTools:
    def test_analyze_market_tool(self, tmp_path):
        data, _ = market(yahoo_payload())
        registry = ToolRegistry(market_tools(data, Workspace(tmp_path)))
        result = registry.execute(ToolCall("t1", "analyze_market", {
            "source": "yahoo", "symbol": "GC=F", "history_days": 60, "horizon_days": 14,
        }))
        assert not result.is_error, result.output
        payload = json.loads(result.output)
        assert payload["symbol"] == "GC=F"
        assert payload["forecast"]["horizon_days"] == 14
        assert "не инвестиционный совет" in payload["note"]

    def test_network_error_returned_to_model(self, tmp_path):
        def offline(url):
            raise MarketDataError("Нет связи с источником данных")

        registry = ToolRegistry(market_tools(MarketData(fetch=offline), Workspace(tmp_path)))
        result = registry.execute(ToolCall("t1", "analyze_market", {
            "source": "cbr", "symbol": "USD", "history_days": 30, "horizon_days": 7,
        }))
        assert result.is_error
        assert "Нет связи" in result.output

    def test_horizon_limit(self, tmp_path):
        registry = ToolRegistry(market_tools(market()[0], Workspace(tmp_path)))
        result = registry.execute(ToolCall("t1", "analyze_market", {
            "source": "cbr", "symbol": "USD", "history_days": 30, "horizon_days": 5000,
        }))
        assert result.is_error

    def test_analyze_price_csv(self, tmp_path):
        lines = ["Date,Close"] + [f"2026-09-{d:02d},{100 + d}" for d in range(1, 26)]
        (tmp_path / "prices.csv").write_text("\n".join(lines))
        registry = ToolRegistry(market_tools(market()[0], Workspace(tmp_path)))
        result = registry.execute(
            ToolCall("t1", "analyze_price_csv", {"path": "prices.csv", "horizon_days": 7})
        )
        assert not result.is_error, result.output
        assert json.loads(result.output)["last_price"] == 125

    def test_cashflow_tool(self, tmp_path):
        (tmp_path / "bank.csv").write_text("дата;сумма\n01.09.2026;1000\n10.09.2026;-300\n")
        registry = ToolRegistry([cashflow_tool(Workspace(tmp_path))])
        result = registry.execute(ToolCall("t1", "analyze_cashflow", {
            "path": "bank.csv", "opening_balance": 500, "horizon_days": 30,
        }))
        assert not result.is_error, result.output
        assert json.loads(result.output)["closing_balance"] == 1200
