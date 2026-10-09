# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""MCP-сервер: список инструментов и вызовы (без сети)."""

import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from cli.mcp_server import Paths, build_server  # noqa: E402
from prizolov_os.memory import Store  # noqa: E402
from tests.test_portfolio import MultiMarket  # noqa: E402
from tests.test_tenders import RSS  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def call(server, name, **arguments):
    result = asyncio.run(server.call_tool(name, arguments))
    if isinstance(result, tuple):  # mcp 1.x: (content, structured)
        result = result[0]
    content = getattr(result, "content", result)
    if getattr(result, "is_error", False) or getattr(result, "isError", False):
        raise RuntimeError(content[0].text)
    text = "".join(getattr(c, "text", "") for c in content)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


@pytest.fixture
def server(tmp_path):
    (tmp_path / "bank.txt").write_bytes((EXAMPLES / "demo_bank_statement_1c.txt").read_bytes())
    (tmp_path / "v1.md").write_text("Оплата в течение 30 дней.\n", encoding="utf-8")
    (tmp_path / "v2.md").write_text("Оплата в течение 5 дней.\n", encoding="utf-8")
    (tmp_path / "portfolio.csv").write_text("ticker;quantity\nSBER;10\n", encoding="utf-8")
    return build_server(tmp_path, Store(), market=MultiMarket(),
                        tenders_fetch=lambda url: RSS)


def test_tools_listed(server):
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert {"market_forecast", "analyze_bank_statement", "payment_calendar_add",
            "portfolio_analysis", "search_tenders", "compare_documents", "read_document",
            "search_documents", "forecast_accuracy"} <= names
    assert all(t.description for t in tools)


def test_calls(server):
    forecast = call(server, "market_forecast", symbol="GOLD", horizons="7,30")
    assert [f["horizon_days"] for f in forecast["forecasts"]] == [7, 30]
    added = call(server, "payment_calendar_add", title="Зарплата", amount=-900000,
                 due_date="05.10.2026", repeat="ежемесячно")
    assert added["category"] == "Зарплата"
    statement = call(server, "analyze_bank_statement", path="bank.txt", days=60)
    assert statement["source_format"] == "1c"
    assert statement["payment_calendar"]["gap"]["date"] == "2026-10-05"
    diff = call(server, "compare_documents", old_path="v1.md", new_path="v2.md")
    assert "[-30-] {+5+}" in diff["changes"][0]["diff"]
    assert call(server, "portfolio_analysis", path="portfolio.csv")["positions"][0][
        "symbol"] == "SBER"
    tenders = call(server, "search_tenders", query="мебель")
    assert tenders["found"] == 2 and tenders["tenders"][0]["number"] == "0373100000126000123"
    assert call(server, "payment_calendar_list")["payments"][0]["title"] == "Зарплата"
    assert call(server, "search_documents", query="оплата")["results"]
    assert call(server, "forecast_accuracy")["pending"] == 2


def test_paths_are_restricted(tmp_path):
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws" / "a.txt").write_text("x")
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "b.txt").write_text("y")
    paths = Paths(tmp_path / "ws")
    assert paths.resolve("a.txt").name == "a.txt"
    with pytest.raises(PermissionError):
        paths.resolve(str(tmp_path / "other" / "b.txt"))
    with pytest.raises(PermissionError):
        paths.resolve("../other/b.txt")
    assert Paths(tmp_path / "ws", [tmp_path / "other"]).resolve(
        str(tmp_path / "other" / "b.txt")).name == "b.txt"
    with pytest.raises(FileNotFoundError):
        paths.resolve("none.txt")


def test_errors_are_readable(server):
    with pytest.raises(Exception, match="разрешённых папок"):
        call(server, "read_document", path="/etc/passwd")
    with pytest.raises(Exception, match="horizons"):
        call(server, "market_forecast", symbol="GOLD", horizons="0")
