# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Тесты самосовершенствования: критик, уроки, промпты, инструменты агентов."""

import json

import pytest

from prizolov_os.improvement import (
    Critic,
    LessonExtractor,
    PromptImprover,
    UnsafeCodeError,
    build_tool,
    check_code,
    format_lessons,
    propose_tool_tool,
    revision_request,
    run_sandboxed,
)
from prizolov_os.llm import FakeLLMClient, LLMResponse, ToolCall
from prizolov_os.memory import Lesson, Store
from prizolov_os.tools import ToolRegistry


def lesson(text, agent="director"):
    return Lesson(1, agent, text, "critic", "")


class TestCritic:
    def test_parses_review_and_sends_schema(self):
        llm = FakeLLMClient([json.dumps({"score": 5, "issues": ["Нет источника"], "lesson": "x"})])
        review = Critic(llm).review("задача", "ответ", ["[market] данные"])
        assert (review.score, review.issues, review.lesson) == (5, ["Нет источника"], "x")
        call = llm.calls[0]
        assert call["output_schema"]["required"] == ["score", "issues", "lesson"]
        prompt = call["messages"][0]["content"]
        assert "[market] данные" in prompt and "ответ" in prompt

    def test_needs_revision(self):
        critic = Critic(FakeLLMClient(), threshold=7)
        assert critic.needs_revision(type("R", (), {"score": 5, "issues": ["a"]})())
        assert not critic.needs_revision(type("R", (), {"score": 5, "issues": []})())
        assert not critic.needs_revision(type("R", (), {"score": 8, "issues": ["a"]})())

    def test_score_clamped(self):
        llm = FakeLLMClient([json.dumps({"score": 42, "issues": [], "lesson": ""})])
        assert Critic(llm).review("t", "a").score == 10

    @pytest.mark.parametrize("reply", [
        "не json",
        LLMResponse(content=[], stop_reason="refusal", model="fake"),
    ])
    def test_failure_treated_as_acceptable(self, reply):
        assert Critic(FakeLLMClient([reply])).review("t", "a").score == 10

    def test_revision_request_lists_issues(self):
        review = Critic(FakeLLMClient([json.dumps(
            {"score": 4, "issues": ["Нет даты", "Нет оговорки"], "lesson": ""}
        )])).review("t", "a")
        text = revision_request(review)
        assert "- Нет даты" in text and "- Нет оговорки" in text


class TestLessonExtractor:
    def test_extracts(self):
        llm = FakeLLMClient([json.dumps({"agent": "writer", "lesson": "Пиши короче"})])
        result = LessonExtractor(llm).from_feedback(
            "задача", "ответ", False, "слишком длинно", ["director", "writer"]
        )
        assert (result.agent, result.text) == ("writer", "Пиши короче")
        enum = llm.calls[0]["output_schema"]["properties"]["agent"]["enum"]
        assert enum == ["director", "writer"]

    def test_empty_lesson(self):
        llm = FakeLLMClient([json.dumps({"agent": "director", "lesson": " "})])
        assert LessonExtractor(llm).from_feedback("t", "a", True, "ок", ["director"]) is None

    def test_format_lessons(self):
        assert format_lessons([]) == ""
        assert "- Учитывай НДС" in format_lessons([lesson("Учитывай НДС")])


class TestPromptImprover:
    def test_proposal_with_diff(self):
        llm = FakeLLMClient([json.dumps({
            "prompt": "Ты агент.\nУчитывай НДС.", "changes": ["Добавлено правило про НДС"]
        })])
        proposal = PromptImprover(llm).propose("director", "Ты агент.", [lesson("Учитывай НДС")])
        assert proposal.prompt.endswith("Учитывай НДС.")
        assert "+Учитывай НДС." in proposal.diff
        assert proposal.changes == ["Добавлено правило про НДС"]

    def test_requires_lessons(self):
        with pytest.raises(ValueError):
            PromptImprover(FakeLLMClient()).propose("a", "p", [])


VAT_CODE = "def run(amount, rate):\n    return round(amount * (1 + rate / 100), 2)\n"


class TestSandbox:
    def test_runs_allowed_code(self):
        assert run_sandboxed(VAT_CODE, {"amount": 100, "rate": 20}) == 120.0

    @pytest.mark.parametrize("code, reason", [
        ("import os\ndef run():\n    return 1", "os"),
        ("import subprocess\ndef run():\n    return 1", "subprocess"),
        ("def run():\n    return open('/etc/passwd').read()", "open"),
        ("def run():\n    return eval('1')", "eval"),
        ("def run():\n    return ().__class__", "__class__"),
        ("import calendar\ndef run():\n    return calendar.sys", "sys"),
        ("import re\ndef run():\n    return re.enum", "enum"),
        ("def g():\n    yield 1\ndef run():\n    return g().gi_frame", "gi_frame"),
        ("def helper():\n    return 1", "run"),
        ("def run(:\n    pass", "Синтаксическая"),
    ])
    def test_rejects_unsafe_code(self, code, reason):
        with pytest.raises(UnsafeCodeError, match=reason):
            check_code(code)

    def test_allows_datetime_time(self):
        assert run_sandboxed(
            "import datetime\ndef run():\n    return str(datetime.time(9, 30))", {}
        ) == "09:30:00"

    def test_timeout(self):
        with pytest.raises(RuntimeError, match="дольше"):
            run_sandboxed("def run():\n    while True:\n        pass", {}, timeout=1)

    def test_runtime_error(self):
        with pytest.raises(RuntimeError, match="ZeroDivisionError"):
            run_sandboxed("def run():\n    return 1 / 0", {})


class TestProposeTool:
    def propose(self, store, **overrides):
        params = {
            "name": "vat_calc",
            "description": "Сумма с НДС",
            "parameters_json": json.dumps({
                "amount": {"type": "number", "description": "Сумма"},
                "rate": {"type": "number", "description": "Ставка, %"},
            }),
            "code": VAT_CODE,
            **overrides,
        }
        registry = ToolRegistry([propose_tool_tool(store, lambda: ["calculator"])])
        return registry.execute(ToolCall("t1", "propose_tool", params))

    def test_saved_as_pending_then_built(self):
        store = Store()
        result = self.propose(store)
        assert not result.is_error, result.output
        record = store.get_custom_tool("vat_calc")
        assert record.status == "pending"
        assert record.input_schema["required"] == ["amount", "rate"]

        tool = build_tool(record)
        out = ToolRegistry([tool]).execute(ToolCall("t2", "vat_calc", {"amount": 50, "rate": 10}))
        assert out.output == "55.0"
        assert tool.description.startswith("[Создан агентом]")

    @pytest.mark.parametrize("overrides, message", [
        ({"name": "calculator"}, "уже существует"),
        ({"name": "Bad Name"}, "Имя"),
        ({"parameters_json": "{oops"}, "некорректный JSON"),
        ({"parameters_json": '{"x": {"type": "object"}}'}, "type"),
        ({"code": "import os\ndef run(amount, rate):\n    return 1"}, "запрещён"),
    ])
    def test_rejects_bad_proposals(self, overrides, message):
        store = Store()
        result = self.propose(store, **overrides)
        assert result.is_error
        assert message in result.output
        assert store.list_custom_tools() == []
