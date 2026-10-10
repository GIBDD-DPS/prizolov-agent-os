# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Тесты постоянной памяти."""

import pytest

from prizolov_os.memory import ACTIVE, ARCHIVED, PENDING, Store, keyword_score, stems


@pytest.fixture
def store():
    return Store()


class TestSearch:
    def test_stems_handle_word_forms(self):
        assert stems("золото") == stems("золота")
        assert keyword_score("цена золота", "Золото подорожало, цена выросла") == 2

    def test_short_words_ignored(self):
        assert stems("и в на") == set()


class TestSessions:
    def test_save_load_and_list(self, store):
        messages = [{"role": "user", "content": "привет"}, {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "", "signature": "s"},
            {"type": "text", "text": "Здравствуйте"},
        ]}]
        store.save_session("s1", messages, title="Привет")
        assert store.load_session("s1") == messages
        info = store.list_sessions()[0]
        assert (info.id, info.title, info.messages) == ("s1", "Привет", 2)

    def test_update_keeps_title(self, store):
        store.save_session("s1", [], title="Первый")
        store.save_session("s1", [{"role": "user", "content": "x"}], title="Другой")
        assert store.list_sessions()[0].title == "Первый"
        assert len(store.load_session("s1")) == 1

    def test_missing_and_delete(self, store):
        assert store.load_session("nope") is None
        store.save_session("s1", [])
        assert store.delete_session("s1")
        assert store.list_sessions() == []

    def test_persists_on_disk(self, tmp_path):
        path = tmp_path / "sub" / "db.sqlite"
        Store(path).add_fact("Компания на УСН")
        assert Store(path).list_facts()[0].text == "Компания на УСН"


class TestFacts:
    def test_add_search_dedupe_delete(self, store):
        first = store.add_fact("Компания работает по УСН 6%")
        assert store.add_fact("Компания работает по УСН 6%") == first
        store.add_fact("Основной клиент - ООО Ромашка")
        assert [f.text for f in store.search_facts("налоговый режим УСН")] == [
            "Компания работает по УСН 6%"
        ]
        assert store.delete_fact(first)
        assert len(store.list_facts()) == 1

    def test_empty_fact(self, store):
        with pytest.raises(ValueError):
            store.add_fact("  ")

    def test_remember_and_recall_tools(self, store):
        from prizolov_os.tools import memory_tools

        tools = {t.name: t for t in memory_tools(store)}
        assert tools["remember"].handler(fact="Компания работает по УСН 6%") == "Запомнено (#1)"
        assert tools["recall"].handler(query="УСН") == "- Компания работает по УСН 6%"
        assert tools["recall"].handler(query="аренда") == "В памяти ничего не найдено"
        assert tools["recall"].untrusted


class TestLessons:
    def test_relevant_lessons_by_agent(self, store):
        store.add_lesson("director", "При расчёте цен учитывай НДС 20%", "feedback-")
        store.add_lesson("director", "Отвечай кратко", "critic")
        store.add_lesson("writer", "Цены пиши с НДС", "feedback-")
        found = store.relevant_lessons("director", "посчитай цену с НДС")
        assert [lesson.text for lesson in found] == ["При расчёте цен учитывай НДС 20%"]
        assert len(store.list_lessons("director")) == 2
        assert len(store.list_lessons()) == 3

    def test_lessons_since_last_prompt(self, store):
        store.add_lesson("a", "урок 1", "critic")
        assert store.lessons_since_last_prompt("a") == 1
        store.activate_prompt(store.propose_prompt("a", "новый промпт"))
        assert store.lessons_since_last_prompt("a") == 0
        store.add_lesson("a", "урок 2", "critic")
        assert store.lessons_since_last_prompt("a") == 1


class TestPromptVersions:
    def test_activate_archives_previous(self, store):
        v1 = store.propose_prompt("a", "v1")
        v2 = store.propose_prompt("a", "v2")
        store.activate_prompt(v1)
        store.activate_prompt(v2)
        assert store.active_prompt("a").prompt == "v2"
        assert store.get_prompt_version(v1).status == ARCHIVED

    def test_rollback(self, store):
        v1 = store.propose_prompt("a", "v1")
        store.activate_prompt(v1)
        store.activate_prompt(store.propose_prompt("a", "v2"))
        assert store.rollback_prompt("a").prompt == "v1"
        assert store.active_prompt("a").id == v1
        assert store.rollback_prompt("a") is None
        assert store.active_prompt("a") is None

    def test_rollback_without_versions(self, store):
        with pytest.raises(ValueError):
            store.rollback_prompt("a")

    def test_reject_and_cannot_activate_rejected(self, store):
        v1 = store.propose_prompt("a", "v1")
        store.reject_prompt(v1)
        with pytest.raises(ValueError):
            store.activate_prompt(v1)
        assert store.get_prompt_version(v1).status != ACTIVE


class TestCustomTools:
    def test_lifecycle(self, store):
        schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
        store.add_custom_tool("vat_calc", "НДС", schema, "def run(): return 1")
        record = store.get_custom_tool("vat_calc")
        assert record.status == PENDING
        assert record.input_schema == schema
        store.set_custom_tool_status("vat_calc", "approved")
        with pytest.raises(ValueError, match="уже подключён"):
            store.add_custom_tool("vat_calc", "НДС", schema, "def run(): return 2")
        assert [t.name for t in store.list_custom_tools("approved")] == ["vat_calc"]

    def test_unknown_tool_status(self, store):
        with pytest.raises(ValueError):
            store.set_custom_tool_status("nope", "approved")
