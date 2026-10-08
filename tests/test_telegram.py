# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Тесты Telegram-бота (без сети: Telegram имитируется)."""

import json
import threading
import time

import pytest

from cli.telegram.bot import build_application, parse_allowed_ids
from cli.telegram.format import split_message, to_telegram_html
from cli.telegram.service import TelegramService
from prizolov_os.core.kernel import Kernel
from prizolov_os.llm import FakeLLMClient, tool_use_response
from prizolov_os.memory import Store

OWNER, STRANGER, CHAT = 111, 999, 5


class FakeIO:
    def __init__(self):
        self.sent, self.edits, self.buttons, self.photos = [], [], [], []
        self._ids = iter(range(1, 10_000))
        self.lock = threading.Lock()

    def send_text(self, chat_id, text, html=False):
        with self.lock:
            self.sent.append((chat_id, text, html))
            return next(self._ids)

    def edit_text(self, chat_id, message_id, text):
        self.edits.append((message_id, text))

    def send_buttons(self, chat_id, text, buttons):
        with self.lock:
            self.buttons.append((chat_id, text, buttons))
            return next(self._ids)

    def send_photo(self, chat_id, path, caption=""):
        self.photos.append((chat_id, path.name, caption))

    def texts(self):
        return [t for _, t, _ in self.sent]


def make_service(tmp_path, responses, store=None, **kwargs):
    store = store or Store()
    io = FakeIO()
    llm = FakeLLMClient(responses)

    def factory(**kw):
        return Kernel.create(llm=llm, store=store, self_check="off", **kw)

    service = TelegramService(io, factory, {OWNER}, tmp_path, **kwargs)
    return service, io, llm


class TestAccess:
    def test_stranger_denied_and_nothing_runs(self, tmp_path):
        service, io, llm = make_service(tmp_path, ["секрет"])
        service.handle_text(CHAT, STRANGER, "покажи документы")
        service.handle_command(CHAT, STRANGER, "/facts")
        service.handle_document(CHAT, STRANGER, "a.txt", b"x")
        assert all("Доступ запрещён" in t for t in io.texts())
        assert str(STRANGER) in io.texts()[0]
        assert llm.calls == []
        assert not (tmp_path / "inbox").exists()

    def test_stranger_cannot_press_buttons(self, tmp_path):
        service, _, _ = make_service(tmp_path, [])
        assert service.resolve_approval("approve:abc:yes", STRANGER) == "Доступ запрещён"

    def test_parse_allowed_ids(self):
        assert parse_allowed_ids(" 1, 2;3 ") == {1, 2, 3}
        assert parse_allowed_ids("") == set()
        with pytest.raises(ValueError):
            parse_allowed_ids("1,abc")


class TestChat:
    def test_answer_with_progress_and_cost(self, tmp_path):
        service, io, _ = make_service(tmp_path, [
            tool_use_response("delegate", {"agent": "assistant", "task": "Посчитай 2+2"}),
            "4", "**Ответ:** 4",
        ])
        service.handle_text(CHAT, OWNER, "Сколько будет 2+2?")
        assert io.sent[0][1] == "⏳ Думаю…"
        assert io.sent[-1] == (CHAT, "<b>Ответ:</b> 4", True)
        final_status = io.edits[-1][1]
        assert "Ассистент закончил" in final_status and "✓ Готово" in final_status

    def test_history_kept_per_chat_and_resumed(self, tmp_path):
        store = Store()
        service, _, llm = make_service(tmp_path, ["Привет, Анна", "Анна"], store=store)
        service.handle_text(CHAT, OWNER, "Я Анна")
        assert store.load_session(f"tg-{CHAT}")
        again, _, llm2 = make_service(tmp_path, ["Вы Анна"], store=store)
        again.handle_text(CHAT, OWNER, "Кто я?")
        assert len(llm2.calls[0]["messages"]) == 3

    def test_busy_chat(self, tmp_path):
        service, io, _ = make_service(tmp_path, [])
        chat = service._chat(CHAT)
        chat.busy.acquire()
        service.handle_text(CHAT, OWNER, "ещё")
        assert "Ещё работаю" in io.texts()[-1]

    def test_model_error_reported(self, tmp_path):
        from prizolov_os.llm import LLMError

        service, io, llm = make_service(tmp_path, [])

        def boom(**_):
            raise LLMError("Нет соединения с Anthropic API")

        llm.complete = boom
        service.handle_text(CHAT, OWNER, "x")
        assert "Нет соединения" in io.edits[-1][1]


class TestApproval:
    def run_write(self, tmp_path, answer, timeout=5.0):
        service, io, _ = make_service(tmp_path, [
            tool_use_response("delegate", {"agent": "writer", "task": "сохрани"}),
            tool_use_response("write_file", {"path": "note.md", "content": "текст"}),
            "готово", "Итог",
        ], approval_timeout=timeout)
        worker = threading.Thread(target=service.handle_text, args=(CHAT, OWNER, "запиши"))
        worker.start()
        deadline = time.monotonic() + 5
        while not io.buttons and time.monotonic() < deadline:
            time.sleep(0.01)
        if answer is not None:
            data = io.buttons[0][2][0 if answer else 1][1]
            assert service.resolve_approval(data, OWNER) == ("Разрешено" if answer else "Отклонено")
        worker.join(10)
        return service, io

    def test_allowed(self, tmp_path):
        _, io = self.run_write(tmp_path, True)
        assert "note.md" in io.buttons[0][1] and "текст" in io.buttons[0][1]
        assert (tmp_path / "note.md").read_text().startswith("текст")

    def test_denied(self, tmp_path):
        self.run_write(tmp_path, False)
        assert not (tmp_path / "note.md").exists()

    def test_timeout_denies(self, tmp_path):
        _, io = self.run_write(tmp_path, None, timeout=0.2)
        assert not (tmp_path / "note.md").exists()
        assert any("действие отклонено" in t for t in io.texts())

    def test_stale_button(self, tmp_path):
        service, _, _ = make_service(tmp_path, [])
        assert service.resolve_approval("approve:deadbeef:yes", OWNER) == "Запрос уже неактуален"
        assert service.resolve_approval("hack", OWNER) == "Неизвестная кнопка"


class TestDocumentsAndCommands:
    def test_upload_saved_indexed_and_mentioned(self, tmp_path):
        service, io, llm = make_service(tmp_path, ["Прочитал"])
        service.handle_document(CHAT, OWNER, "../../Договор поставки.txt", "Скидка 7%".encode())
        saved = tmp_path / "inbox" / "Договор_поставки.txt"
        assert saved.read_text() == "Скидка 7%"
        assert "добавлен в базу знаний" in io.texts()[-1]
        assert service._chat(CHAT).kernel.knowledge.search("скидка")[0].path.startswith("inbox/")
        service.handle_text(CHAT, OWNER, "Что в файле?")
        first = llm.calls[0]["messages"][0]["content"]
        assert "[Пользователь прислал файл: inbox/Договор_поставки.txt]" in first

    def test_upload_with_caption_runs_task(self, tmp_path):
        service, io, llm = make_service(tmp_path, ["Сводка"])
        service.handle_document(CHAT, OWNER, "a.csv", b"x", caption="Сделай сводку")
        assert "Сводка" in io.texts()[-1]
        assert "Сделай сводку" in llm.calls[0]["messages"][0]["content"]

    def test_upload_rejected_types_and_names_unique(self, tmp_path):
        service, io, _ = make_service(tmp_path, [])
        service.handle_document(CHAT, OWNER, "virus.exe", b"x")
        assert "Поддерживаются" in io.texts()[-1]
        service.handle_document(CHAT, OWNER, "a.txt", b"1")
        service.handle_document(CHAT, OWNER, "a.txt", b"2")
        assert (tmp_path / "inbox" / "a-2.txt").read_text() == "2"

    def test_commands(self, tmp_path):
        service, io, _ = make_service(tmp_path, [])
        service.handle_command(CHAT, OWNER, "/help")
        assert "Prizolov Agent OS" in io.texts()[-1]
        service.handle_command(CHAT, OWNER, "/cost")
        assert io.sent[-1][1].startswith("<pre>Последняя задача")
        service.handle_command(CHAT, OWNER, "/approve-tool x")
        assert "только в CLI" in io.texts()[-1]
        service.handle_text(CHAT, OWNER, "/facts@my_bot")
        assert "Фактов пока нет" in io.texts()[-1]

    def test_chart_photos_sent(self, tmp_path):
        (tmp_path / "bank.csv").write_text("дата;сумма\n01.09.2026;1000\n10.09.2026;-300\n")
        service, io, _ = make_service(tmp_path, [
            tool_use_response("delegate", {"agent": "cashflow_analyst", "task": "графики"}),
            tool_use_response("chart_cashflow", {
                "path": "bank.csv", "opening_balance": 0, "horizon_days": 14,
            }),
            "нарисовал", "Вот графики",
        ])
        service.handle_text(CHAT, OWNER, "Нарисуй графики")
        assert len(io.photos) == 2
        assert all(name.endswith(".png") for _, name, _ in io.photos)


class TestFormat:
    def test_markdown_to_html(self):
        html = to_telegram_html(
            "# Итог\n**жирно** и *курсив*, `код`, <тег> & [сайт](https://x.ru)\n- пункт"
        )
        assert "<b>Итог</b>" in html and "<b>жирно</b>" in html and "<i>курсив</i>" in html
        assert "<code>код</code>" in html and "&lt;тег&gt; &amp;" in html
        assert '<a href="https://x.ru">сайт</a>' in html and "• пункт" in html

    def test_code_block(self):
        assert to_telegram_html("```python\nx = 1 < 2\n```") == "<pre>x = 1 &lt; 2</pre>"

    def test_split(self):
        text = ("абзац " * 50 + "\n\n") * 40
        parts = split_message(text, 1000)
        assert all(len(p) <= 1000 for p in parts)
        def squash(value):
            return value.replace(" ", "").replace("\n", "")

        assert squash("".join(parts)) == squash(text)


def test_application_builds_offline(tmp_path):
    application = build_application("123:abc", {OWNER}, tmp_path)
    assert len(application.handlers[0]) == 3


def test_chart_output_json_parsed():
    from cli.telegram.service import _Progress

    progress = _Progress(FakeIO(), CHAT, 1)
    from prizolov_os import events as ev
    from prizolov_os.events import Event

    progress.on_event(Event(ev.TOOL_RESULT, "x", {
        "tool": "chart_market", "is_error": False, "output": json.dumps({"chart": "charts/a.png"}),
    }))
    assert progress.charts == ["charts/a.png"]
