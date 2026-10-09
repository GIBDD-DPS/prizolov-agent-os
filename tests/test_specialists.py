# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Тесты специалистов."""

import json

import pytest

from prizolov_os.agents import (
    create_cashflow_analyst,
    create_market_analyst,
    create_researcher,
    create_specialists,
    create_writer,
)
from prizolov_os.llm import FakeLLMClient, tool_use_response
from prizolov_os.market import MarketData
from prizolov_os.security import unwrap


@pytest.fixture
def specialists(tmp_path):
    return create_specialists(llm=FakeLLMClient(), workspace_dir=tmp_path)


def test_all_specialists_created(specialists):
    assert list(specialists) == [
        "assistant", "researcher", "writer", "cashflow_analyst", "market_analyst",
        "lawyer",
    ]
    for agent in specialists.values():
        assert agent.description
        assert "Общие правила" in agent.system_prompt


@pytest.mark.parametrize(
    "name, expected_tools",
    [
        ("assistant", {"calculator", "current_datetime", "list_files", "read_file", "write_file"}),
        ("researcher", {"web_search", "web_fetch", "list_files", "read_file", "current_datetime"}),
        ("writer", {"list_files", "read_file", "write_file"}),
        ("cashflow_analyst", {"analyze_cashflow", "chart_cashflow", "calculator",
                              "current_datetime", "list_files", "read_file"}),
        ("market_analyst", {"analyze_market", "analyze_price_csv", "chart_market",
                            "analyze_portfolio", "calculator", "current_datetime",
                            "list_files", "read_file"}),
    ],
)
def test_tool_sets(specialists, name, expected_tools):
    assert set(specialists[name].tools.names()) == expected_tools


def test_only_writers_can_write(specialists):
    writers = {n for n, a in specialists.items() if "write_file" in a.tools}
    assert writers == {"assistant", "writer", "lawyer"}


def test_researcher_sends_server_tools(tmp_path):
    agent = create_researcher(llm=FakeLLMClient(["итог"]), workspace_dir=tmp_path)
    agent.run("найди")
    types = {t.get("type") for t in agent.llm.calls[0]["tools"]}
    assert {"web_search_20260209", "web_fetch_20260209"} <= types


def test_market_analyst_end_to_end(tmp_path):
    from tests.test_market import TODAY, FakeFetch, yahoo_payload

    market = MarketData(fetch=FakeFetch(yahoo_payload()), today=lambda: TODAY)
    llm = FakeLLMClient([
        tool_use_response("analyze_market", {
            "source": "yahoo", "symbol": "GC=F", "history_days": 60, "horizon_days": 30,
        }),
        "Золото растёт. Это не инвестиционная рекомендация.",
    ])
    agent = create_market_analyst(llm=llm, workspace_dir=tmp_path, market=market)
    result = agent.run("Что будет с золотом через месяц?")

    assert result.completed
    assert not result.tool_results[0].is_error
    sent = llm.calls[1]["messages"][-1]["content"][0]["content"]
    assert json.loads(sent)["forecast"]["horizon_days"] == 30


def test_cashflow_analyst_end_to_end(tmp_path):
    (tmp_path / "bank.csv").write_text("дата;сумма\n01.09.2026;1000\n15.09.2026;-400\n")
    llm = FakeLLMClient([
        tool_use_response("analyze_cashflow", {
            "path": "bank.csv", "opening_balance": 0, "horizon_days": 30,
        }),
        "Остаток 600.",
    ])
    result = create_cashflow_analyst(llm=llm, workspace_dir=tmp_path).run("Проанализируй")
    assert json.loads(unwrap(result.tool_results[0].output))["closing_balance"] == 600


def test_writer_needs_approval_to_save(tmp_path):
    llm = FakeLLMClient([
        tool_use_response("write_file", {"path": "post.md", "content": "Текст"}),
        "Сохранить не удалось.",
    ])
    create_writer(llm=llm, workspace_dir=tmp_path).run("Напиши и сохрани пост")
    assert not (tmp_path / "post.md").exists()
