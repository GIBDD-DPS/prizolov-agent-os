# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Открытая статистика точности прогнозов."""

import argparse
import io

import pytest
from rich.console import Console

from prizolov_os.__about__ import PROJECT_ID
from prizolov_os.accuracy import accuracy_data, render_html
from prizolov_os.config import settings
from prizolov_os.forecasting import ForecastEngine, ForecastJournal
from prizolov_os.memory import Store
from prizolov_os.reports import market_report
from tests.test_reports import StubMarket


def store_with_verified():
    store = Store()
    journal = ForecastJournal(store)
    market_report(StubMarket(), ForecastEngine(journal), "GOLD", horizons=[1, 7, 30])
    for i, forecast in enumerate(journal.pending()):
        actual = forecast.median if i != 1 else forecast.high_80 * 1.5  # одна мимо
        journal.mark_verified(forecast, actual)
    return store


def test_empty_store():
    data = accuracy_data(Store())
    assert data["overall"]["forecasts"] == 0 and data["pending"] == 0
    page = render_html(data)
    assert "Пока нет прогнозов" in page and PROJECT_ID in page


def test_counts_and_groups():
    data = accuracy_data(store_with_verified())
    overall = data["overall"]
    assert overall["forecasts"] == 3
    assert overall["interval_80_pct"] == pytest.approx(66.7)
    assert data["by_asset_class"][0]["name"] == "драгметаллы"
    assert {g["key"] for g in data["by_horizon"]} == {"до 7 дн.", "до 30 дн."}
    assert data["by_symbol"][0]["key"] == "GOLD"
    assert len(data["recent"]) == 3 and sum(r["hit_80"] for r in data["recent"]) == 2


def test_page_escapes_and_signs():
    data = accuracy_data(store_with_verified())
    data["by_symbol"][0]["name"] = "<script>x</script>"
    page = render_html(data)
    assert "<script>x" not in page and "&lt;script&gt;" in page
    assert "Dm.Andreyanov" in page and "Факт в интервале 80%" in page


def test_cli_writes_page(tmp_path, monkeypatch):
    from cli.main import run_accuracy

    monkeypatch.setattr(settings, "db_path", str(tmp_path / "db.sqlite"))
    out = io.StringIO()
    target = tmp_path / "site" / "accuracy.html"
    assert run_accuracy(Console(file=out, width=200), argparse.Namespace(out=str(target))) == 0
    assert target.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert "Сверенных прогнозов пока нет" in out.getvalue()


def test_public_endpoint_is_opt_in(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from cli.api.server import create_app
    from cli.api.service import ApiService
    from prizolov_os.core.kernel import Kernel
    from prizolov_os.llm import FakeLLMClient

    store = store_with_verified()

    def factory(**kw):
        return Kernel.create(llm=FakeLLMClient([]), store=store, self_check="off", **kw)

    key = "test-key-0123456789abcdef"
    closed = TestClient(create_app(ApiService(factory, tmp_path), {key}))
    assert closed.get("/public/accuracy").status_code == 404
    data = closed.get("/v1/accuracy", headers={"X-API-Key": key}).json()
    assert data["overall"]["forecasts"] == 3
    opened = TestClient(create_app(ApiService(factory, tmp_path), {key}, public_accuracy=True))
    page = opened.get("/public/accuracy")
    assert page.status_code == 200 and "default-src 'none'" in page.headers[
        "Content-Security-Policy"]
    assert opened.get("/public/accuracy.json").json()["overall"]["forecasts"] == 3
