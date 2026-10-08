# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Тесты стоимости, лимитов расходов и журнала трассировки."""

import io
import json
from datetime import date

import pytest
from rich.console import Console

from cli.app import ChatApp
from prizolov_os import events as ev
from prizolov_os.__about__ import PROJECT_ID
from prizolov_os.budget import Budget, BudgetExceeded, MeteredLLM, cost, price_for
from prizolov_os.core.kernel import Kernel
from prizolov_os.events import EventBus
from prizolov_os.llm import FakeLLMClient, LLMError, Usage, text_response, tool_use_response
from prizolov_os.memory import Store
from prizolov_os.tracing import Tracer


def priced(text, input_tokens=0, output_tokens=0, model="claude-sonnet-5-5", **extra):
    response = text_response(text)
    response.model = model
    response.usage = Usage(input_tokens=input_tokens, output_tokens=output_tokens, **extra)
    return response


class TestCost:
    def test_sonnet_prices(self):
        usage = Usage(input_tokens=1_000_000, output_tokens=100_000,
                      cache_read_input_tokens=1_000_000, cache_creation_input_tokens=1_000_000)
        # 2 + 1 (выход) + 0.20 (чтение кэша) + 2.50 (запись кэша)
        assert cost(usage, "claude-sonnet-5-5") == pytest.approx(5.70)

    def test_web_search(self):
        assert cost(Usage(web_search_requests=3), "claude-sonnet-5-5") == pytest.approx(0.03)

    def test_model_lookup(self):
        assert price_for("claude-opus-5-5").output == 20.0
        assert price_for("claude-haiku-4-5-20251001").input == 1.0
        assert price_for("unknown-model") == price_for("claude-sonnet-5-5")


class TestBudget:
    def test_metered_adds_cost_and_tracks_day(self):
        budget = Budget(Store(), task_limit_usd=1, day_limit_usd=10)
        llm = MeteredLLM(FakeLLMClient([priced("ok", 100_000, 10_000)]), budget)
        response = llm.complete(system="s", messages=[])
        assert response.usage.cost_usd == pytest.approx(0.30)
        assert budget.task_spent_usd == pytest.approx(0.30)
        assert budget.today_spent_usd() == pytest.approx(0.30)
        assert budget.history()[0]["requests"] == 1

    def test_task_limit_blocks_next_request(self):
        budget = Budget(Store(), task_limit_usd=0.5, day_limit_usd=0)
        llm = MeteredLLM(FakeLLMClient([priced("a", 300_000), priced("b")]), budget)
        llm.complete(system="s", messages=[])
        with pytest.raises(BudgetExceeded, match="лимит расходов на задачу"):
            llm.complete(system="s", messages=[])
        budget.start_task()
        llm.complete(system="s", messages=[])

    def test_day_limit_survives_restart(self):
        store = Store()
        Budget(store).add(10.5)
        budget = Budget(store, task_limit_usd=0, day_limit_usd=10)
        with pytest.raises(BudgetExceeded, match="дневной лимит"):
            budget.check()
        assert issubclass(BudgetExceeded, LLMError)

    def test_days_are_separate(self):
        store, day = Store(), [date(2026, 10, 7)]
        budget = Budget(store, task_limit_usd=0, day_limit_usd=1, today=lambda: day[0])
        budget.add(2)
        day[0] = date(2026, 10, 8)
        budget.check()
        assert budget.total_spent_usd() == 2

    def test_zero_means_unlimited(self):
        budget = Budget(Store(), task_limit_usd=0, day_limit_usd=0)
        budget.add(1000)
        budget.check()


def make_kernel(tmp_path, responses, **kwargs):
    return Kernel.create(llm=FakeLLMClient(responses), store=Store(), workspace_dir=tmp_path,
                         self_check="off", **kwargs)


class TestKernelBudget:
    def test_answer_cost_includes_specialists(self, tmp_path, monkeypatch):
        from prizolov_os.config import settings

        monkeypatch.setattr(settings, "budget_task_usd", 0.0)
        kernel = make_kernel(tmp_path, [
            tool_use_response("delegate", {"agent": "assistant", "task": "x"}),
            priced("r", 1_000_000),
            priced("итог", 0, 100_000),
        ])
        result = kernel.chat("задача")
        assert result.usage.cost_usd == pytest.approx(3.0)  # 2 (ассистент) + 1 (Директор)

    def test_limit_stops_task_and_resets_for_next(self, tmp_path, monkeypatch):
        from prizolov_os.config import settings

        monkeypatch.setattr(settings, "budget_task_usd", 1.0)
        monkeypatch.setattr(settings, "budget_day_usd", 0.0)
        kernel = make_kernel(tmp_path, [
            tool_use_response("delegate", {"agent": "assistant", "task": "x"}),
            priced("дорого", 2_000_000),
            "Ответ без доработки",
        ])
        with pytest.raises(BudgetExceeded):
            kernel.chat("задача")
        assert kernel.chat("следующая").text == "Ответ без доработки"


class TestTracer:
    def test_writes_events_with_session_and_truncation(self, tmp_path):
        bus = EventBus()
        tracer = Tracer(tmp_path, session=lambda: "s1")
        tracer.attach(bus)
        bus.emit(ev.TOOL_CALL, "writer", tool="write_file",
                 input={"path": "a.md", "content": "x" * 1000}, server=False)
        bus.emit(ev.LLM_RESPONSE, "writer", stop_reason="end_turn", model="m",
                 usage=Usage(input_tokens=5, cost_usd=0.01))
        lines = tracer.path.read_text().splitlines()
        first, second = (json.loads(line) for line in lines)
        assert first["session"] == "s1" and first["agent"] == "writer"
        assert first["project"] == PROJECT_ID
        content = first["data"]["input"]["content"]
        assert content.startswith("xxx") and "+800 симв." in content
        assert second["data"]["usage"]["cost_usd"] == 0.01

    def test_full_content_mode(self, tmp_path):
        bus = EventBus()
        Tracer(tmp_path, include_content=True).attach(bus)
        bus.emit(ev.DELEGATION_START, "director", specialist="writer", task="y" * 500)
        record = json.loads(next(tmp_path.glob("trace-*.jsonl")).read_text())
        assert record["data"]["task"] == "y" * 500

    def test_kernel_traces_a_run(self, tmp_path):
        kernel = Kernel.create(llm=FakeLLMClient(["ok"]), store=Store(), workspace_dir=tmp_path,
                               self_check="off", trace=True)
        kernel.tracer.directory = tmp_path / "logs"
        kernel.chat("привет")
        records = [json.loads(line) for line in kernel.tracer.path.read_text().splitlines()]
        assert [r["type"] for r in records] == ["llm_request", "llm_response"]
        assert records[0]["session"] == kernel.session_id


class TestCli:
    def run(self, kernel, *commands):
        out = io.StringIO()
        app = ChatApp(kernel, Console(file=out, width=150, color_system=None), lambda _: "")
        for command in commands:
            app.handle(command)
        return out.getvalue()

    def test_cost_and_budget_commands(self, tmp_path):
        kernel = make_kernel(tmp_path, [priced("ok", 500_000)])
        kernel.chat("x")
        out = self.run(kernel, "/cost", "/budget task 2,5", "/budget day 0", "/budget week 3")
        assert "Последняя задача: $1.00" in out
        assert "Лимит на задачу: $2.50, на день: без лимита" in out
        assert "Формат: /budget task" in out
        assert kernel.budget.task_limit_usd == 2.5

    def test_budget_message_is_not_model_error(self, tmp_path):
        kernel = make_kernel(tmp_path, [])
        kernel.budget.day_limit_usd = 1
        kernel.budget.add(5)
        out = self.run(kernel, "привет")
        assert "дневной лимит" in out and "Ошибка модели" not in out
