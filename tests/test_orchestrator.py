# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Тесты оркестратора (Директора)."""

import pytest

from prizolov_os.agent import Agent
from prizolov_os.core.orchestrator import Orchestrator
from prizolov_os.llm import FakeLLMClient, Usage, text_response, tool_use_response


def specialist(name, responses, description="d"):
    return Agent(role=name, name=name, description=description, llm=FakeLLMClient(responses))


def delegate(agent, task, tool_id="d1"):
    return tool_use_response("delegate", {"agent": agent, "task": task}, tool_id=tool_id)


class TestInit:
    def test_prompt_lists_team(self):
        orch = Orchestrator([specialist("researcher", [], "ищет факты")], llm=FakeLLMClient())
        assert "- researcher: ищет факты" in orch.director.system_prompt
        schema = orch.director.tools.schemas()[0]
        assert schema["input_schema"]["properties"]["agent"]["enum"] == ["researcher"]

    def test_accepts_dict(self):
        agents = {"a": specialist("a", [])}
        assert list(Orchestrator(agents, llm=FakeLLMClient()).specialists) == ["a"]

    def test_without_specialists_director_has_no_tools(self):
        orch = Orchestrator(llm=FakeLLMClient())
        assert len(orch.director.tools) == 0
        assert orch.execution_log == []


class TestRun:
    def test_answers_directly(self):
        orch = Orchestrator([specialist("a", [])], llm=FakeLLMClient(["Привет!"]))
        result = orch.run("Привет")
        assert result.text == "Привет!"
        assert orch.get_execution_log() == []

    def test_pipeline_research_then_write(self):
        researcher = specialist("researcher", ["Факт: золото выросло на 20%"])
        writer = specialist("writer", ["Пост: золото выросло на 20%!"])
        director_llm = FakeLLMClient([
            delegate("researcher", "Найди динамику золота", "d1"),
            delegate("writer", "Напиши пост по фактам: Факт: золото выросло на 20%", "d2"),
            "Готово: Пост: золото выросло на 20%!",
        ])
        orch = Orchestrator([researcher, writer], llm=director_llm)
        result = orch.run("Исследуй золото и напиши пост")

        assert result.completed
        assert researcher.llm.calls[0]["messages"][0]["content"] == "Найди динамику золота"
        tool_result = director_llm.calls[1]["messages"][-1]["content"][0]
        assert tool_result["content"] == "Факт: золото выросло на 20%"
        assert [d.agent for d in orch.get_execution_log()] == ["researcher", "writer"]
        assert all(d.status == "end_turn" for d in orch.get_execution_log())

    def test_unknown_specialist_reported_to_director(self):
        orch = Orchestrator(
            [specialist("a", [])],
            llm=FakeLLMClient([delegate("ghost", "x"), "Не получилось"]),
        )
        result = orch.run("задача")
        assert result.tool_results[0].is_error
        assert "одним из" in result.tool_results[0].output

    def test_unfinished_specialist_flagged(self):
        looping = Agent(
            role="a", name="a", max_iterations=1,
            llm=FakeLLMClient([tool_use_response("nope", {})]),
        )
        orch = Orchestrator([looping], llm=FakeLLMClient([delegate("a", "x"), "итог"]))
        result = orch.run("задача")
        assert "не завершил задачу: max_iterations" in result.tool_results[0].output
        assert orch.get_execution_log()[0].status == "max_iterations"

    def test_specialist_exception_logged_and_returned(self):
        broken = specialist("a", [])
        broken.run = lambda task: (_ for _ in ()).throw(RuntimeError("упал"))
        orch = Orchestrator([broken], llm=FakeLLMClient([delegate("a", "x"), "итог"]))
        result = orch.run("задача")
        assert result.tool_results[0].is_error
        assert orch.get_execution_log()[0].status == "error"

    def test_delegation_limit(self):
        director = FakeLLMClient(
            [delegate("a", "x", f"d{i}") for i in range(3)] + ["итог"]
        )
        orch = Orchestrator(
            [specialist("a", ["r1", "r2", "r3"])], llm=director, max_delegations=2
        )
        result = orch.run("задача")
        assert [r.is_error for r in result.tool_results] == [False, False, True]
        assert "Лимит поручений" in result.tool_results[2].output
        assert len(orch.get_execution_log()) == 2

    def test_limit_resets_between_runs(self):
        director = FakeLLMClient([delegate("a", "x"), "1", delegate("a", "y"), "2"])
        orch = Orchestrator([specialist("a", ["r1", "r2"])], llm=director, max_delegations=1)
        orch.run("первая")
        assert not orch.run("вторая").tool_results[0].is_error

    def test_usage_includes_specialists(self):
        spec_answer = text_response("r")
        spec_answer.usage = Usage(input_tokens=100, output_tokens=10)
        first = delegate("a", "x")
        first.usage = Usage(input_tokens=5, output_tokens=1)
        orch = Orchestrator([specialist("a", [spec_answer])], llm=FakeLLMClient([first, "итог"]))
        result = orch.run("задача")
        assert result.usage.input_tokens == 105
        assert orch.get_execution_log()[0].usage.input_tokens == 100

    @pytest.mark.parametrize("task", ["", "   ", None])
    def test_invalid_task(self, task):
        with pytest.raises(ValueError, match="Task must be a non-empty string"):
            Orchestrator(llm=FakeLLMClient()).run(task)


class TestChat:
    def test_keeps_history_and_reset(self):
        orch = Orchestrator(llm=FakeLLMClient(["Привет, Анна", "Анна"]))
        orch.chat("Я Анна")
        orch.chat("Как меня зовут?")
        assert len(orch.director.history) == 4
        orch.reset()
        assert orch.director.history == []

    def test_execute_and_clear_log(self):
        orch = Orchestrator(
            [specialist("a", ["r"])], llm=FakeLLMClient([delegate("a", "x"), "итог"])
        )
        assert orch.execute("задача") == "итог"
        orch.clear_log()
        assert orch.get_execution_log() == []
