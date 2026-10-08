"""Тесты самообучения на ошибках прогнозов."""

import io
import math
import random
from datetime import date, timedelta

import pytest
from rich.console import Console

from cli.app import ChatApp
from prizolov_os import events as ev
from prizolov_os.analytics import parse_cashflow_csv
from prizolov_os.analytics.timeseries import Z80
from prizolov_os.core.kernel import Kernel
from prizolov_os.events import EventBus
from prizolov_os.forecasting import (
    ForecastEngine,
    ForecastJournal,
    asset_class,
    backtest,
    best_method,
    calibrate,
    horizon_bucket,
    predict,
)
from prizolov_os.forecasting.backtest import coverage
from prizolov_os.llm import FakeLLMClient
from prizolov_os.market import MarketDataError, PriceSeries
from prizolov_os.memory import Store
from prizolov_os.quality import ALERT_MIN_CALLS, QualityMonitor

START = date(2025, 10, 1)


def random_walk(n=300, drift=0.0005, vol=0.01, seed=1, start=100.0):
    rng = random.Random(seed)
    prices = [start]
    for _ in range(n):
        prices.append(prices[-1] * math.exp(rng.gauss(drift, vol)))
    return prices


def dates(n):
    return [START + timedelta(days=i) for i in range(n)]


class TestMethods:
    def test_intervals_ordered(self):
        p = predict(random_walk(), 20, "recent_trend")
        assert p.low_95 < p.low_80 < p.median < p.high_80 < p.high_95

    def test_no_trend_keeps_price(self):
        prices = random_walk()
        p = predict(prices, 20, "no_trend")
        assert p.median == pytest.approx(prices[-1])
        assert p.probability_up == pytest.approx(0.5)

    def test_scale_and_bias(self):
        prices = random_walk()
        base = predict(prices, 20, "no_trend")
        wide = predict(prices, 20, "no_trend", scale=2.0)
        shifted = predict(prices, 20, "no_trend", bias=0.5)
        assert wide.high_80 - wide.low_80 > base.high_80 - base.low_80
        assert shifted.median > base.median

    def test_unknown_method(self):
        with pytest.raises(ValueError):
            predict(random_walk(), 5, "magic")


class TestBacktest:
    def test_counts_and_rates(self):
        stats = backtest(random_walk(), 20)
        for s in stats.values():
            assert s.n > 30
            assert 0 <= s.pass_rate_80 <= 1
            assert len(s.z) == s.n
        assert stats["no_trend"].direction_n == 0  # без тренда направление не прогнозирует

    def test_too_short_history(self):
        stats = backtest(random_walk(20), 10)
        assert all(s.n == 0 for s in stats.values())
        assert best_method(stats) == "trend"

    def test_picks_reversion_on_mean_reverting_series(self):
        rng = random.Random(3)
        prices = [100 + 8 * math.sin(i / 6) + rng.gauss(0, 0.3) for i in range(400)]
        assert best_method(backtest(prices, 10)) in {"mean_reversion", "recent_trend"}


class TestCalibration:
    def test_needs_samples(self):
        calib = calibrate([0.1] * 5)
        assert not calib.applied and calib.scale == 1.0

    def test_widens_overconfident_intervals(self):
        rng = random.Random(4)
        z = [rng.gauss(0, 2) for _ in range(200)]  # ошибки вдвое шире заявленных
        calib = calibrate(z)
        assert calib.applied and calib.scale > 1.5
        assert coverage(z, calib.scale, calib.bias, Z80) == pytest.approx(0.8, abs=0.05)

    def test_corrects_bias_within_bounds(self):
        calib = calibrate([3.0] * 20)
        assert calib.bias == 0.5  # не больше границы

    def test_scale_bounded(self):
        assert calibrate([50.0, -50.0] * 10).scale == 2.0


class TestClassify:
    @pytest.mark.parametrize("source, symbol, expected", [
        ("cbr", "GOLD", "metal"), ("cbr", "USD", "fx"), ("moex", "SBER", "stock_ru"),
        ("yahoo", "GC=F", "metal"), ("yahoo", "BZ=F", "commodity"), ("yahoo", "EURUSD=X", "fx"),
        ("yahoo", "BTC-USD", "crypto"), ("yahoo", "^GSPC", "index"), ("yahoo", "AAPL", "stock"),
        ("csv", "prices.csv", "custom"),
    ])
    def test_asset_class(self, source, symbol, expected):
        assert asset_class(source, symbol) == expected

    def test_bucket(self):
        assert horizon_bucket(7) == "до 7 дн." and horizon_bucket(365) == "больше 90 дн."


def make_journal():
    return ForecastJournal(Store())


def record(journal, **overrides):
    params = dict(
        kind="market", source="cbr", symbol="USD", asset_class="fx", bucket="до 30 дн.",
        method="trend", horizon_days=30, base_date=date(2026, 9, 1), base_value=90.0,
        median=91.0, raw_median=91.0, base_spread=0.03, low_80=88.0, high_80=94.0,
        low_95=86.0, high_95=96.0, probability_up=0.6,
    )
    params.update(overrides)
    return journal.record(**params)


class TestJournal:
    def test_due_and_verify(self):
        journal = make_journal()
        record(journal)
        assert journal.due(date(2026, 9, 30)) == []
        forecast = journal.due(date(2026, 10, 1))[0]
        verified = journal.mark_verified(forecast, 95.0)
        assert verified.status == "verified"
        assert verified.hit_80 is False and verified.direction_ok is True
        assert verified.error_pct == pytest.approx((95 - 91) / 91 * 100)
        assert journal.live_z("fx", "до 30 дн.")[0] == pytest.approx(math.log(95 / 91) / 0.03)
        assert journal.counts() == {"verified": 1}

    def test_cashflow_verification(self):
        journal = make_journal()
        record(journal, kind="cashflow", source="csv", symbol="bank.csv", asset_class="cashflow",
               base_date=date(2026, 9, 10), base_value=1000.0, median=1500.0, raw_median=1500.0,
               base_spread=200.0, low_80=1250.0, high_80=1750.0, horizon_days=10,
               probability_up=None)
        transactions = parse_cashflow_csv(
            "дата;сумма\n01.09.2026;5000\n15.09.2026;300\n20.09.2026;200\n25.09.2026;-50\n"
        )
        verified = journal.verify_cashflow(transactions)
        assert len(verified) == 1
        assert verified[0].actual == 1500.0 and verified[0].hit_80

    def test_cashflow_not_verified_without_coverage(self):
        journal = make_journal()
        record(journal, kind="cashflow", asset_class="cashflow", base_date=date(2026, 9, 10),
               horizon_days=10)
        assert journal.verify_cashflow(parse_cashflow_csv("дата;сумма\n12.09.2026;1\n")) == []

    def test_leaderboard_and_reset(self):
        journal = make_journal()
        stats = backtest(random_walk(), 20)
        journal.save_backtest("cbr", "USD", "fx", "до 30 дн.", stats)
        board = journal.leaderboard()
        assert {row["method"] for row in board} == set(stats)
        assert board[0]["backtest"].n > 0
        assert journal.backtest_z("fx", "до 30 дн.", "trend")
        journal.reset("fx")
        assert journal.backtest_z("fx", "до 30 дн.", "trend") == []


class TestEngine:
    def test_forecast_contains_reliability_and_is_recorded(self):
        journal = make_journal()
        prices = random_walk(365)
        result = ForecastEngine(journal).market_forecast(
            "yahoo", "GC=F", dates(len(prices)), prices, 30
        )
        rel = result["reliability"]
        assert rel["asset_class"] == "драгметаллы"
        assert rel["backtest_forecasts"] > 30
        assert 0 <= rel["backtest_interval_80_pass_pct"] <= 100
        assert rel["expected_interval_80_success_pct"] > 0
        assert "проверен на" in rel["summary"]
        assert result["calibration"]["applied"]
        assert {row["tested_forecasts"] for row in result["method_competition"]} == {
            rel["backtest_forecasts"]
        }
        assert journal.get(result["forecast_id"]).method == result["method"]

    def test_short_history_reports_unknown_reliability(self):
        prices = random_walk(20)
        result = ForecastEngine().market_forecast("cbr", "USD", dates(21), prices, 30)
        assert result["reliability"]["backtest_forecasts"] == 0
        assert "надёжность неизвестна" in result["reliability"]["summary"]
        assert "forecast_id" not in result

    def test_live_results_drive_method_choice(self):
        journal = make_journal()
        for _ in range(10):
            fid = record(journal, method="mean_reversion", asset_class="metal",
                         symbol="GC=F", source="yahoo", median=100.0, raw_median=100.0)
            journal.mark_verified(journal.get(fid), 100.5)
        prices = random_walk(365)
        result = ForecastEngine(journal).market_forecast(
            "yahoo", "GC=F", dates(len(prices)), prices, 30
        )
        assert result["method"] == "mean_reversion"
        assert result["reliability"]["verified_live"]["forecasts"] == 10


class StubMarket:
    def __init__(self, prices):
        self.prices = prices
        self.calls = []

    def history(self, source, symbol, days):
        self.calls.append((source, symbol))
        if symbol == "BROKEN":
            raise MarketDataError("Нет связи")
        return PriceSeries(source, symbol, "RUB", list(self.prices), list(self.prices.values()))


def make_kernel(market, store=None):
    return Kernel.create(llm=FakeLLMClient(), store=store or Store(), market=market,
                         self_check="off")


class TestKernelVerification:
    def test_verifies_with_nearest_previous_price(self):
        market = StubMarket({date(2026, 9, 28): 93.0, date(2026, 9, 30): 92.0})
        kernel = make_kernel(market)
        record(kernel.forecasts, base_date=date(2026, 9, 1), horizon_days=30)  # 1 октября
        report = kernel.verify_forecasts(today=date(2026, 10, 7))
        assert [f.actual for f in report.verified] == [92.0]
        assert market.calls == [("cbr", "USD")]

    def test_network_error_keeps_pending(self):
        kernel = make_kernel(StubMarket({}))
        record(kernel.forecasts, symbol="BROKEN")
        report = kernel.verify_forecasts(today=date(2026, 10, 7))
        assert report.errors and not report.verified
        assert kernel.forecasts.counts() == {"pending": 1}

    def test_gives_up_after_long_time(self):
        kernel = make_kernel(StubMarket({}))
        record(kernel.forecasts, base_date=date(2026, 1, 1))
        report = kernel.verify_forecasts(today=date(2026, 10, 7))
        assert report.unverifiable == 1

    def test_low_accuracy_creates_lesson_once(self):
        market = StubMarket({date(2026, 10, 1): 120.0})
        kernel = make_kernel(market)
        for _ in range(12):
            record(kernel.forecasts)
        kernel.verify_forecasts(today=date(2026, 10, 7))
        lessons = kernel.store.list_lessons("market_analyst")
        assert len(lessons) == 1 and "часто не сбываются" in lessons[0].text
        for _ in range(12):
            record(kernel.forecasts)
        kernel.verify_forecasts(today=date(2026, 10, 7))
        assert len(kernel.store.list_lessons("market_analyst")) == 1


class TestQuality:
    def emit_results(self, bus, ok, count, source="yahoo"):
        for _ in range(count):
            bus.emit(ev.TOOL_RESULT, "market_analyst", tool="analyze_market",
                     input={"source": source}, is_error=not ok, output="")

    def test_tracks_sources_and_alerts_once(self):
        store, bus = Store(), EventBus()
        monitor = QualityMonitor(store, bus)
        self.emit_results(bus, True, ALERT_MIN_CALLS - 4)
        self.emit_results(bus, False, 4)
        self.emit_results(bus, False, 6)
        tools = monitor.tools()
        assert tools[0].key == "analyze_market:yahoo" and tools[0].errors == 10
        lessons = store.list_lessons("market_analyst")
        assert len(lessons) == 1 and "источником yahoo" in lessons[0].text

    def test_no_alert_when_reliable(self):
        store, bus = Store(), EventBus()
        QualityMonitor(store, bus)
        self.emit_results(bus, True, 20)
        self.emit_results(bus, False, 2)
        assert store.list_lessons() == []

    def test_critic_and_feedback_in_report(self):
        store, bus = Store(), EventBus()
        monitor = QualityMonitor(store, bus)
        bus.emit(ev.SELF_CHECK, "critic", score=9, issues=[])
        bus.emit(ev.SELF_CHECK, "critic", score=5, issues=["x"])
        monitor.record_feedback("writer", False)
        report = monitor.report()
        assert report["critic"] == {"checks": 2, "average_score": 7.0, "revisions": 1}
        assert report["feedback"] == {"writer": {"good": 0, "bad": 1}}


class TestCli:
    def app(self, kernel, inputs=()):
        out = io.StringIO()
        answers = list(inputs)
        app = ChatApp(kernel, Console(file=out, width=160, color_system=None),
                      lambda prompt: answers.pop(0))
        return app, out

    def test_forecasts_verify_quality_commands(self):
        market = StubMarket({date(2026, 10, 1): 92.0})
        kernel = make_kernel(market)
        kernel.forecasts.save_backtest("cbr", "USD", "fx", "до 30 дн.",
                                       backtest(random_walk(), 20))
        app, out = self.app(kernel)
        app.handle("/forecasts")
        assert "Соревнование методов" in out.getvalue()
        assert "валюты" in out.getvalue()

        record(kernel.forecasts, base_date=date.today() - timedelta(days=40))
        market.prices = {date.today() - timedelta(days=10): 92.0}
        app.handle("/verify")
        assert "Сверено прогнозов: 1" in out.getvalue()

        app.handle("/quality")
        assert "Статистики пока нет" in out.getvalue()

    def test_calibration_reset_confirms(self):
        kernel = make_kernel(StubMarket({}))
        app, out = self.app(kernel, ["y"])
        app.handle("/calibration-reset валюты")
        assert "Калибровка сброшена" in out.getvalue()
        app.handle("/calibration-reset марсиане")
        assert "Неизвестный класс" in out.getvalue()
