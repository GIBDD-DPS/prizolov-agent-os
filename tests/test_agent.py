# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Тесты агента (через FakeLLMClient, без сети)."""

import pytest

from prizolov_os.agent import Agent
from prizolov_os.llm import FakeLLMClient, LLMResponse, Usage, text_response, tool_use_response
from prizolov_os.tools import Tool, calculator_tool, make_schema


def make_agent(responses=None, **kwargs):
    return Agent(role="test", llm=FakeLLMClient(responses), **kwargs)


class TestAgentInit:
    def test_create_with_role(self):
        agent = make_agent()
        assert agent.role == "test"
        assert agent.name == "test"
        assert agent.constraints == {}
        assert agent.memory == []
        assert "test" in agent.system_prompt

    def test_custom_system_prompt_and_name(self):
        agent = make_agent(system_prompt="Ты бот.", name="bot")
        assert agent.system_prompt == "Ты бот."
        assert agent.name == "bot"

    def test_llm_created_lazily(self):
        agent = Agent(role="test")
        assert agent._llm is None


class TestAgentApplyConstraints:
    def test_valid_input(self):
        assert make_agent().apply_constraints("hello world") == "hello world"

    @pytest.mark.parametrize("value", [None, 123, ["hello"]])
    def test_non_string_input(self, value):
        with pytest.raises(TypeError, match="Expected input_data to be str"):
            make_agent().apply_constraints(value)

    def test_forbidden_token(self):
        agent = make_agent(constraints={"forbidden_tokens": ["bad"]})
        with pytest.raises(ValueError, match="Forbidden token 'bad'"):
            agent.apply_constraints("this is bad input")

    def test_forbidden_token_blocks_run_before_llm(self):
        agent = make_agent(constraints={"forbidden_tokens": ["bad"]})
        with pytest.raises(ValueError):
            agent.run("this is bad")
        assert agent.llm.calls == []


class TestAgentRun:
    def test_plain_answer(self):
        agent = make_agent(["Ответ"])
        result = agent.run("Вопрос")
        assert result.text == "Ответ"
        assert result.completed
        assert result.iterations == 1
        call = agent.llm.calls[0]
        assert call["messages"] == [{"role": "user", "content": "Вопрос"}]
        assert call["tools"] is None
        assert call["system"] == agent.system_prompt

    def test_tool_loop(self):
        agent = make_agent(
            [tool_use_response("calculator", {"expression": "6*7"}, tool_id="t1"), "Будет 42"],
            tools=[calculator_tool()],
        )
        result = agent.run("Сколько будет 6*7?")

        assert result.text == "Будет 42"
        assert result.iterations == 2
        assert result.tool_results[0].output == "42"
        second = agent.llm.calls[1]
        assert second["tools"][0]["name"] == "calculator"
        assert second["messages"][-1] == {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "42"}],
        }

    def test_parallel_tool_calls_in_one_message(self):
        both = LLMResponse(
            content=[
                {"type": "tool_use", "id": i, "name": "calculator", "input": {"expression": e}}
                for i, e in [("a", "1+1"), ("b", "2+2")]
            ],
            stop_reason="tool_use",
            model="fake",
        )
        agent = make_agent([both, "готово"], tools=[calculator_tool()])
        agent.run("посчитай")
        results = agent.llm.calls[1]["messages"][-1]["content"]
        assert [r["content"] for r in results] == ["2", "4"]

    def test_tool_error_returned_to_model(self):
        agent = make_agent(
            [tool_use_response("calculator", {"expression": "1/0"}), "Деление на ноль"],
            tools=[calculator_tool()],
        )
        result = agent.run("1/0")
        assert result.tool_results[0].is_error
        assert result.text == "Деление на ноль"

    def test_iteration_limit(self):
        loop = [tool_use_response("calculator", {"expression": "1"}) for _ in range(5)]
        agent = make_agent(loop, tools=[calculator_tool()], max_iterations=3)
        result = agent.run("зациклись")
        assert result.stop_reason == "max_iterations"
        assert result.iterations == 3
        assert "лимит" in result.text

    def test_refusal(self):
        agent = make_agent([LLMResponse(content=[], stop_reason="refusal", model="fake")])
        result = agent.run("что-то")
        assert result.stop_reason == "refusal"
        assert not result.completed

    def test_max_tokens_closes_pending_tool_calls(self):
        cut = tool_use_response("calculator", {"expression": "1"}, tool_id="t9")
        cut.stop_reason = "max_tokens"
        agent = make_agent([cut], tools=[calculator_tool()])
        agent.chat("длинная задача")
        assert result_is_closed(agent.history, "t9")

    def test_pause_turn_continues_without_user_message(self):
        paused = text_response("ищу...")
        paused.stop_reason = "pause_turn"
        agent = make_agent([paused, "нашёл"])
        result = agent.run("найди")
        assert result.text == "нашёл"
        assert agent.llm.calls[1]["messages"][-1]["role"] == "assistant"

    def test_usage_summed(self):
        first = tool_use_response("calculator", {"expression": "1"})
        first.usage = Usage(input_tokens=10, output_tokens=2)
        second = text_response("ok")
        second.usage = Usage(input_tokens=15, output_tokens=3, cache_read_input_tokens=8)
        result = make_agent([first, second], tools=[calculator_tool()]).run("x")
        assert (result.usage.input_tokens, result.usage.output_tokens) == (25, 5)
        assert result.usage.cache_read_input_tokens == 8

    def test_run_does_not_touch_history(self):
        agent = make_agent(["a"])
        agent.run("q")
        assert agent.history == []


class TestApproval:
    def make_tool(self, calls):
        return Tool(
            name="danger",
            description="d",
            input_schema=make_schema({"x": {"type": "string"}}),
            handler=lambda x: calls.append(x) or "сделано",
            requires_approval=True,
        )

    def test_denied_without_approver(self):
        calls = []
        agent = make_agent(
            [tool_use_response("danger", {"x": "1"}), "не дали"], tools=[self.make_tool(calls)]
        )
        result = agent.run("сделай")
        assert calls == []
        assert result.tool_results[0].is_error
        assert "не разрешил" in result.tool_results[0].output

    def test_approver_sees_call_and_allows(self):
        calls, asked = [], []

        def approver(name, tool_input):
            asked.append((name, tool_input))
            return True

        agent = make_agent(
            [tool_use_response("danger", {"x": "1"}), "готово"],
            tools=[self.make_tool(calls)],
            approver=approver,
        )
        agent.run("сделай")
        assert asked == [("danger", {"x": "1"})]
        assert calls == ["1"]


class TestChat:
    def test_keeps_history(self):
        agent = make_agent(["Привет, Анна", "Вас зовут Анна"])
        agent.chat("Меня зовут Анна")
        agent.chat("Как меня зовут?")
        messages = agent.llm.calls[1]["messages"]
        assert [m["role"] for m in messages] == ["user", "assistant", "user"]
        assert messages[0]["content"] == "Меня зовут Анна"

    def test_refusal_rolls_back_turn(self):
        agent = make_agent(["ok", LLMResponse(content=[], stop_reason="refusal", model="fake")])
        agent.chat("первое")
        agent.chat("плохое")
        assert len(agent.history) == 2

    def test_reset(self):
        agent = make_agent(["ok"])
        agent.chat("hi")
        agent.reset()
        assert agent.history == []


class TestCompatibility:
    def test_execute_returns_text_and_records_memory(self):
        agent = make_agent(["результат"])
        assert agent.execute("task1") == "результат"
        assert agent.get_memory() == [("task1", "результат")]

    def test_clear_memory(self):
        agent = make_agent()
        agent.execute("task1")
        agent.clear_memory()
        assert agent.get_memory() == []


def result_is_closed(history, tool_use_id):
    last = history[-1]
    return last["role"] == "user" and last["content"][0]["tool_use_id"] == tool_use_id
