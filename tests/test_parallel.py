# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Тесты параллельных поручений и потокобезопасности."""

import threading
import time

from prizolov_os.agent import Agent
from prizolov_os.budget import Budget
from prizolov_os.core.kernel import Kernel
from prizolov_os.core.orchestrator import Orchestrator
from prizolov_os.llm import FakeLLMClient, LLMResponse, text_response
from prizolov_os.memory import Store
from prizolov_os.tools import Tool, make_schema, serialized

DELAY = 0.3


def calls_response(name, inputs):
    return LLMResponse(
        content=[{"type": "tool_use", "id": f"c{i}", "name": name, "input": data}
                 for i, data in enumerate(inputs)],
        stop_reason="tool_use", model="fake",
    )


def slow_tool(name="slow"):
    def handler(x: str) -> str:
        time.sleep(DELAY)
        return f"done {x}"

    return Tool(name, "d", make_schema({"x": {"type": "string"}}), handler)


class SlowLLM(FakeLLMClient):
    def complete(self, **kwargs):
        time.sleep(DELAY)
        return super().complete(**kwargs)


class TestAgentParallel:
    def make(self, max_parallel, parallel_tools=("slow",), extra_tools=()):
        llm = FakeLLMClient([
            calls_response("slow", [{"x": "a"}, {"x": "b"}, {"x": "c"}]), "итог"
        ])
        agent = Agent(role="r", llm=llm, tools=[slow_tool(), *extra_tools])
        agent.parallel_tools, agent.max_parallel = set(parallel_tools), max_parallel
        return agent

    def test_runs_concurrently_and_keeps_order(self):
        agent = self.make(max_parallel=4)
        start = time.monotonic()
        result = agent.run("x")
        elapsed = time.monotonic() - start
        assert elapsed < DELAY * 2
        assert [r.output for r in result.tool_results] == ["done a", "done b", "done c"]
        sent = agent.llm.calls[1]["messages"][-1]["content"]
        assert [b["tool_use_id"] for b in sent] == ["c0", "c1", "c2"]

    def test_sequential_when_disabled(self):
        agent = self.make(max_parallel=1)
        start = time.monotonic()
        agent.run("x")
        assert time.monotonic() - start >= DELAY * 3

    def test_sequential_for_tools_not_marked_parallel(self):
        agent = self.make(max_parallel=4, parallel_tools=())
        start = time.monotonic()
        agent.run("x")
        assert time.monotonic() - start >= DELAY * 3


def specialist(name):
    return Agent(role=name, name=name, description="d", llm=SlowLLM([f"ответ {name}"]))


def delegate_calls(agents):
    return calls_response("delegate", [{"agent": a, "task": f"задача {a}"} for a in agents])


class TestOrchestratorParallel:
    def test_delegations_run_concurrently(self):
        names = ["gold", "usd", "btc"]
        orch = Orchestrator(
            [specialist(n) for n in names],
            llm=FakeLLMClient([delegate_calls(names), "сводка"]),
        )
        orch.director.parallel_tools, orch.director.max_parallel = {"delegate"}, 4
        start = time.monotonic()
        result = orch.run("три актива")
        assert time.monotonic() - start < DELAY * 2
        assert [r.output for r in result.tool_results] == ["ответ gold", "ответ usd", "ответ btc"]
        assert sorted(d.agent for d in orch.get_execution_log()) == sorted(names)

    def test_limit_holds_under_concurrency(self):
        names = [f"a{i}" for i in range(6)]
        orch = Orchestrator(
            [specialist(n) for n in names],
            llm=FakeLLMClient([delegate_calls(names), "итог"]),
            max_delegations=2,
        )
        orch.director.parallel_tools, orch.director.max_parallel = {"delegate"}, 6
        result = orch.run("много")
        assert sum(not r.is_error for r in result.tool_results) == 2
        assert sum("Лимит поручений" in r.output for r in result.tool_results) == 4
        assert len(orch.get_execution_log()) == 2

    def test_usage_summed_across_threads(self):
        names = ["a", "b", "c", "d"]
        agents = []
        for n in names:
            response = text_response("ok")
            response.usage.input_tokens = 10
            agents.append(Agent(role=n, name=n, llm=FakeLLMClient([response])))
        orch = Orchestrator(agents, llm=FakeLLMClient([delegate_calls(names), "итог"]))
        orch.director.parallel_tools, orch.director.max_parallel = {"delegate"}, 4
        assert orch.run("x").usage.input_tokens == 40


def test_serialized_approver_asks_one_at_a_time():
    active, peak, lock = [0], [0], threading.Lock()

    def approver(name, params):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return True

    ask = serialized(approver)
    threads = [threading.Thread(target=ask, args=("write_file", {})) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak[0] == 1
    assert serialized(None) is None


def test_budget_thread_safe():
    budget = Budget(Store(), task_limit_usd=0, day_limit_usd=0)
    threads = [threading.Thread(target=lambda: [budget.add(0.01) for _ in range(50)])
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert round(budget.task_spent_usd, 6) == 4.0
    assert round(budget.today_spent_usd(), 6) == 4.0


def test_kernel_enables_parallel_delegation(tmp_path, monkeypatch):
    from prizolov_os.config import settings

    monkeypatch.setattr(settings, "parallel", 3)
    kernel = Kernel.create(llm=FakeLLMClient(), store=Store(), workspace_dir=tmp_path)
    director = kernel.orchestrator.director
    assert director.parallel_tools == {"delegate"} and director.max_parallel == 3
    assert "одновременно" in director.system_prompt
