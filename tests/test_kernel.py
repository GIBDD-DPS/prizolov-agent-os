# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Тесты ядра: диалоги, самопроверка, уроки, версии промптов, инструменты агентов."""

import json

import pytest

from prizolov_os.core.kernel import PROMPT_IMPROVEMENT_THRESHOLD, Kernel
from prizolov_os.core.orchestrator import Orchestrator
from prizolov_os.llm import FakeLLMClient, tool_use_response
from prizolov_os.memory import Store

VAT_CODE = "def run(amount):\n    return amount * 1.2\n"


def delegate(agent="assistant", task="Посчитай 2+2", tool_id="d1"):
    return tool_use_response("delegate", {"agent": agent, "task": task}, tool_id=tool_id)


def review(score, issues=(), lesson=""):
    return json.dumps({"score": score, "issues": list(issues), "lesson": lesson})


def make_kernel(tmp_path, responses, **kwargs):
    kwargs.setdefault("self_check", "off")
    kwargs.setdefault("store", Store())
    return Kernel.create(llm=FakeLLMClient(responses), workspace_dir=tmp_path, **kwargs)


class TestBasics:
    def test_direct_construction(self):
        orchestrator = Orchestrator(llm=FakeLLMClient())
        kernel = Kernel(orchestrator)
        assert kernel.orchestrator is orchestrator
        assert kernel.mode == "standard"
        assert kernel.self_check == "off"

    def test_invalid_self_check_mode(self):
        with pytest.raises(ValueError):
            Kernel(Orchestrator(llm=FakeLLMClient()), self_check="sometimes")

    def test_create_builds_team_and_director_tools(self, tmp_path):
        kernel = make_kernel(tmp_path, [])
        status = kernel.get_status()
        assert status["specialists"] == [
            "assistant", "researcher", "writer", "cashflow_analyst", "market_analyst",
            "lawyer", "tender_analyst",
        ]
        assert set(kernel.orchestrator.director.tools.names()) == {
            "delegate", "remember", "recall", "propose_tool", "search_knowledge", "schedule_task"
        }

    def test_run_delegates(self, tmp_path):
        kernel = make_kernel(tmp_path, [delegate(), "4", "Ответ: 4"])
        result = kernel.run("Сколько будет 2+2?")
        assert result.text == "Ответ: 4"
        assert kernel.get_status()["delegations"] == 1

    @pytest.mark.parametrize("task", ["", None])
    def test_invalid_task(self, task):
        with pytest.raises(ValueError, match="Task must be a non-empty string"):
            Kernel(Orchestrator(llm=FakeLLMClient())).run(task)


class TestSessions:
    def test_chat_saved_and_resumed(self, tmp_path):
        store = Store()
        kernel = make_kernel(tmp_path, ["Привет, Анна"], store=store)
        kernel.chat("Меня зовут Анна")
        session_id = kernel.session_id
        assert store.list_sessions()[0].title == "Меня зовут Анна"

        other = make_kernel(tmp_path, ["Вас зовут Анна"], store=store)
        assert other.resume(session_id) == 2
        other.chat("Как меня зовут?")
        sent = other.orchestrator.director.llm.calls[0]["messages"]
        assert sent[0]["content"] == "Меня зовут Анна"
        assert len(store.load_session(session_id)) == 4

    def test_reset_starts_new_session(self, tmp_path):
        kernel = make_kernel(tmp_path, ["a"])
        kernel.chat("1")
        first = kernel.session_id
        kernel.reset()
        assert kernel.session_id != first
        assert kernel.orchestrator.director.history == []

    def test_resume_unknown(self, tmp_path):
        with pytest.raises(ValueError):
            make_kernel(tmp_path, []).resume("nope")

    def test_remember_and_recall(self, tmp_path):
        kernel = make_kernel(tmp_path, [
            tool_use_response("remember", {"fact": "Компания работает по УСН 6%"}),
            "Запомнил",
        ])
        kernel.chat("Мы на УСН 6%")
        assert kernel.store.list_facts()[0].text == "Компания работает по УСН 6%"


class TestSelfCheck:
    def test_complex_mode_skips_simple_answers(self, tmp_path):
        kernel = make_kernel(tmp_path, ["Привет!"], self_check="complex")
        kernel.chat("Привет")
        assert kernel.last_review is None

    def test_good_review_keeps_answer(self, tmp_path):
        kernel = make_kernel(
            tmp_path, [delegate(), "4", "Ответ: 4", review(9)], self_check="complex"
        )
        result = kernel.run("2+2?")
        assert result.text == "Ответ: 4"
        assert kernel.last_review.score == 9
        critic_prompt = kernel.llm.calls[-1]["messages"][0]["content"]
        assert "[assistant] Поручение: Посчитай 2+2" in critic_prompt
        assert "Результат: 4" in critic_prompt

    def test_bad_review_triggers_revision_and_lesson(self, tmp_path):
        kernel = make_kernel(tmp_path, [
            delegate(), "4", "4",
            review(4, ["Нет пояснения"], "Всегда поясняй расчёт"),
            "Ответ: 4, потому что 2+2=4",
        ], self_check="complex")
        result = kernel.chat("2+2?")
        assert result.text == "Ответ: 4, потому что 2+2=4"
        history = kernel.orchestrator.director.history
        assert "[Самопроверка]" in history[-2]["content"]
        assert [lesson.text for lesson in kernel.store.list_lessons("director")] == [
            "Всегда поясняй расчёт"
        ]

    def test_always_mode_checks_simple_answers(self, tmp_path):
        kernel = make_kernel(tmp_path, ["Привет!", review(8)], self_check="always")
        kernel.chat("Привет")
        assert kernel.last_review.score == 8


class TestFeedbackAndLessons:
    def test_negative_feedback_creates_lesson(self, tmp_path):
        kernel = make_kernel(tmp_path, [
            "Цена 100",
            json.dumps({"agent": "director", "lesson": "Указывай цены с НДС"}),
        ])
        kernel.chat("Сколько стоит?")
        lesson = kernel.feedback(positive=False, comment="без НДС")
        assert lesson.text == "Указывай цены с НДС"
        assert lesson.source == "feedback-"

    def test_positive_without_comment_does_nothing(self, tmp_path):
        kernel = make_kernel(tmp_path, ["ok"])
        kernel.chat("x")
        assert kernel.feedback(positive=True) is None

    def test_feedback_before_answer(self, tmp_path):
        with pytest.raises(ValueError):
            make_kernel(tmp_path, []).feedback(positive=False, comment="плохо")

    def test_lessons_added_to_relevant_requests(self, tmp_path):
        store = Store()
        store.add_lesson("director", "Указывай цены с НДС", "feedback-")
        kernel = make_kernel(tmp_path, ["ok", "ok"], store=store)
        kernel.chat("Какие цены у поставщика?")
        sent = kernel.llm.calls[0]["messages"][0]["content"]
        assert "Указывай цены с НДС" in sent and sent.endswith("Какие цены у поставщика?")
        kernel.chat("Привет")
        assert kernel.llm.calls[1]["messages"][-1]["content"] == "Привет"


class TestPromptVersions:
    def test_propose_approve_rollback(self, tmp_path):
        store = Store()
        for i in range(PROMPT_IMPROVEMENT_THRESHOLD):
            store.add_lesson("writer", f"Правило {i}", "critic")
        kernel = make_kernel(tmp_path, [
            json.dumps({"prompt": "Новый промпт писателя", "changes": ["Добавлены правила"]}),
        ], store=store)
        writer = kernel.agents["writer"]
        original = writer.system_prompt
        assert kernel.improvement_candidates() == [("writer", PROMPT_IMPROVEMENT_THRESHOLD)]

        version, proposal = kernel.propose_prompt("writer")
        assert writer.system_prompt == original
        assert "+Новый промпт писателя" in proposal.diff

        kernel.approve_prompt(version.id)
        assert writer.system_prompt == "Новый промпт писателя"
        assert kernel.improvement_candidates() == []

        assert kernel.rollback_prompt("writer") is None
        assert writer.system_prompt == original

    def test_active_prompt_loaded_on_start(self, tmp_path):
        store = Store()
        store.activate_prompt(store.propose_prompt("director", "Свой промпт"))
        kernel = make_kernel(tmp_path, [], store=store)
        assert kernel.orchestrator.director.system_prompt == "Свой промпт"

    def test_unknown_agent(self, tmp_path):
        with pytest.raises(ValueError, match="Нет агента"):
            make_kernel(tmp_path, []).propose_prompt("ghost")


class TestCustomTools:
    def propose(self):
        return tool_use_response("propose_tool", {
            "name": "vat_calc",
            "description": "Сумма с НДС 20%",
            "parameters_json": json.dumps({"amount": {"type": "number", "description": "Сумма"}}),
            "code": VAT_CODE,
        })

    def test_tool_available_only_after_approval(self, tmp_path):
        kernel = make_kernel(tmp_path, [self.propose(), "Предложил инструмент"])
        kernel.chat("Сделай инструмент для НДС")
        director = kernel.orchestrator.director
        assert "vat_calc" not in director.tools
        assert [t.name for t in kernel.pending_tools()] == ["vat_calc"]

        kernel.approve_tool("vat_calc")
        assert "vat_calc" in director.tools
        assert kernel.pending_tools() == []

    def test_approved_tool_loaded_on_start(self, tmp_path):
        store = Store()
        kernel = make_kernel(tmp_path, [self.propose(), "ok"], store=store)
        kernel.chat("Сделай инструмент")
        kernel.approve_tool("vat_calc")
        again = make_kernel(tmp_path, [], store=store)
        assert "vat_calc" in again.orchestrator.director.tools

    def test_reject(self, tmp_path):
        kernel = make_kernel(tmp_path, [self.propose(), "ok"])
        kernel.chat("Сделай инструмент")
        kernel.reject_tool("vat_calc")
        assert kernel.pending_tools() == []
        with pytest.raises(ValueError):
            kernel.approve_tool("vat_calc")
