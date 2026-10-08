"""Тесты командной строки (FakeLLMClient, вывод в строку)."""

import io
import json

import pytest
from rich.console import Console

from cli.main import main
from prizolov_os.core.kernel import Kernel
from prizolov_os.llm import FakeLLMClient, tool_use_response
from prizolov_os.memory import Store


class Session:
    """Прогоняет CLI с заданными ответами модели и вводом пользователя."""

    def __init__(self, tmp_path, responses, inputs=(), store=None):
        self.out = io.StringIO()
        self.console = Console(file=self.out, width=120, color_system=None)
        self.inputs = list(inputs)
        self.prompts = []
        self.llm = FakeLLMClient(responses)
        self.store = store or Store()
        self.tmp_path = tmp_path

    def ask(self, prompt):
        self.prompts.append(prompt)
        if not self.inputs:
            raise EOFError
        return self.inputs.pop(0)

    def factory(self, **kwargs):
        kwargs["self_check"] = kwargs.get("self_check") or "off"
        return Kernel.create(llm=self.llm, workspace_dir=self.tmp_path, store=self.store, **kwargs)

    def run(self, *argv):
        code = main(list(argv), console=self.console, ask=self.ask, kernel_factory=self.factory)
        return code, self.out.getvalue()


def delegate(agent, task):
    return tool_use_response("delegate", {"agent": agent, "task": task})


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setattr("cli.main._has_credentials", lambda: True)


def test_run_prints_answer_progress_and_usage(tmp_path):
    session = Session(tmp_path, [
        delegate("assistant", "Посчитай 2+2"),
        tool_use_response("calculator", {"expression": "2+2"}),
        "4",
        "**Ответ:** 4",
    ])
    code, out = session.run("run", "Сколько", "будет", "2+2?")
    assert code == 0
    assert "→ Директор → Ассистент: Посчитай 2+2" in out
    assert "⚙ Ассистент: calculator(expression=2+2)" in out
    assert "✓ Ассистент закончил" in out
    assert "Ответ: 4" in out
    assert "Токены: вход 0" in out


def test_missing_key_warning(tmp_path, monkeypatch):
    monkeypatch.setattr("cli.main._has_credentials", lambda: False)
    _, out = Session(tmp_path, ["ok"]).run("run", "x")
    assert "ANTHROPIC_API_KEY" in out


def test_chat_loop_and_commands(tmp_path):
    session = Session(
        tmp_path,
        ["Привет!", json.dumps({"agent": "director", "lesson": "Здоровайся по имени"})],
        inputs=["Привет", "/bad не назвал по имени", "/lessons", "/unknown", "/exit"],
    )
    code, out = session.run("chat")
    assert code == 0
    assert "Привет!" in out
    assert "Урок #1 для Директор: Здоровайся по имени" in out
    assert "Неизвестная команда /unknown" in out
    assert session.store.list_lessons()[0].source == "feedback-"


def test_bad_without_comment(tmp_path):
    _, out = Session(tmp_path, ["ok"], inputs=["hi", "/bad"]).run("chat")
    assert "Напишите, что не так" in out


def test_write_file_asks_and_respects_answer(tmp_path):
    write = tool_use_response("write_file", {"path": "note.md", "content": "строка 1\nстрока 2"})
    session = Session(
        tmp_path,
        [delegate("writer", "Сохрани заметку"), write, "Не сохранено", "Готово"],
        inputs=["Сохрани заметку", "n"],
    )
    _, out = session.run("chat")
    assert "Запись в файл: note.md" in out
    assert "строка 1" in out
    assert "Разрешить? [y/N] " in session.prompts
    assert not (tmp_path / "note.md").exists()


def test_write_file_approved(tmp_path):
    write = tool_use_response("write_file", {"path": "note.md", "content": "текст"})
    session = Session(
        tmp_path,
        [delegate("writer", "Сохрани"), write, "Сохранено", "Готово"],
        inputs=["Сохрани", "да"],
    )
    session.run("chat")
    assert (tmp_path / "note.md").read_text() == "текст"


def test_approve_tool_shows_code(tmp_path):
    propose = tool_use_response("propose_tool", {
        "name": "vat_calc",
        "description": "Сумма с НДС",
        "parameters_json": json.dumps({"amount": {"type": "number", "description": "Сумма"}}),
        "code": "def run(amount):\n    return amount * 1.2\n",
    })
    session = Session(
        tmp_path, [propose, "Предложил инструмент"],
        inputs=["Сделай инструмент НДС", "/tools", "/approve-tool vat_calc", "y"],
    )
    _, out = session.run("chat")
    assert "Агент предложил новый инструмент" in out
    assert "return amount * 1.2" in out
    assert "Инструмент подключён" in out
    assert session.store.get_custom_tool("vat_calc").status == "approved"


def test_sessions_and_resume(tmp_path):
    store = Store()
    first = Session(tmp_path, ["Привет, Анна"], inputs=["Я Анна"], store=store)
    first.run("chat")
    session_id = store.list_sessions()[0].id

    _, out = Session(tmp_path, [], store=store).run("sessions")
    assert session_id in out and "Я Анна" in out

    resumed = Session(tmp_path, ["Вы Анна"], inputs=["Кто я?"], store=store)
    _, out = resumed.run("chat", "--session", session_id)
    assert "Диалог продолжен (2 сообщений)" in out
    assert len(resumed.llm.calls[0]["messages"]) == 3


def test_resume_unknown_session(tmp_path):
    code, out = Session(tmp_path, []).run("chat", "--session", "nope")
    assert code == 1
    assert "не найден" in out


def test_self_check_progress(tmp_path):
    session = Session(tmp_path, [
        delegate("assistant", "x"), "r", "итог",
        json.dumps({"score": 9, "issues": [], "lesson": ""}),
    ])
    _, out = session.run("--self-check", "complex", "run", "задача")
    assert "Самопроверка: 9/10" in out
