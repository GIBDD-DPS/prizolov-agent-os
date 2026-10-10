# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Связка с python-telegram-bot: отправка сообщений, обработчики и запуск, без сети."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("telegram")

from telegram.error import BadRequest  # noqa: E402

from cli.telegram import bot as bot_module  # noqa: E402
from cli.telegram.bot import PTBIO, _strip_tags, build_application  # noqa: E402


class FakeBot:
    """Асинхронный бот, который записывает вызовы вместо запросов к Telegram."""

    def __init__(self, reject_html: bool = False) -> None:
        self.calls = []
        self.reject_html = reject_html

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        if parse_mode == "HTML" and self.reject_html:
            raise BadRequest("Can't parse entities")
        if self.reject_html and parse_mode is None and "<" in text:
            raise AssertionError("в запасной отправке не должно быть тегов")
        self.calls.append(("send", chat_id, text, parse_mode, reply_markup))
        return SimpleNamespace(message_id=len(self.calls))

    async def edit_message_text(self, text, chat_id, message_id):
        self.calls.append(("edit", chat_id, message_id, text))

    async def send_photo(self, chat_id, photo, caption=""):
        self.calls.append(("photo", chat_id, photo.read(), caption))


@pytest.fixture
def loop():
    """Цикл событий в отдельном потоке, как у работающего бота."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(5)
    loop.close()


class TestPTBIO:
    def test_send_text_html(self, loop):
        bot = FakeBot()
        io = PTBIO(bot, loop)
        assert io.send_text(1, "<b>привет</b>", html=True) == 1
        assert bot.calls[0][3] == "HTML"

    def test_bad_html_falls_back_to_plain_text(self, loop):
        bot = FakeBot(reject_html=True)
        io = PTBIO(bot, loop)
        io.send_text(1, "<b>итог</b> &amp; выводы", html=True)
        assert bot.calls == [("send", 1, "итог & выводы", None, None)]

    def test_plain_text_error_is_raised(self, loop):
        class Broken(FakeBot):
            async def send_message(self, *args, **kwargs):
                raise BadRequest("Chat not found")

        with pytest.raises(BadRequest):
            PTBIO(Broken(), loop).send_text(1, "текст")

    def test_edit_buttons_and_photo(self, loop, tmp_path):
        bot = FakeBot()
        io = PTBIO(bot, loop)
        io.edit_text(1, 5, "обновлено")
        message_id = io.send_buttons(1, "Подтвердить?", [("Да", "approve:1:yes")])
        photo = tmp_path / "chart.png"
        photo.write_bytes(b"png")
        io.send_photo(1, photo, "г" * 2000)

        assert bot.calls[0] == ("edit", 1, 5, "обновлено")
        markup = bot.calls[1][4]
        assert message_id == 2
        assert markup.inline_keyboard[0][0].callback_data == "approve:1:yes"
        kind, chat_id, data, caption = bot.calls[2]
        assert (kind, data, len(caption)) == ("photo", b"png", 1000)


def test_strip_tags():
    assert _strip_tags("<i>a</i> &lt;b&gt;") == "a <b>"


class FakeService:
    """Подменяет TelegramService: обработчики бота только передают ему данные."""

    instances = []

    def __init__(self, io, kernel_factory, allowed_ids, workspace_dir):
        self.allowed_ids = allowed_ids
        self.calls = []
        FakeService.instances.append(self)

    def start_scheduler(self):
        self.calls.append(("scheduler",))

    def is_allowed(self, user_id):
        return user_id in self.allowed_ids

    def deny(self, chat_id, user_id):
        self.calls.append(("deny", chat_id, user_id))

    def handle_text(self, chat_id, user_id, text):
        self.calls.append(("text", chat_id, user_id, text))

    def handle_document(self, chat_id, user_id, name, data, caption):
        self.calls.append(("document", chat_id, user_id, name, data, caption))

    def resolve_approval(self, data, user_id):
        self.calls.append(("approval", data, user_id))
        return "Принято"


@pytest.fixture
def app(monkeypatch, tmp_path):
    FakeService.instances = []
    monkeypatch.setattr(bot_module, "TelegramService", FakeService)
    application = build_application("123:ABC", {7}, tmp_path)
    handlers = {h.callback.__name__: h.callback for h in application.handlers[0]}
    return application, handlers


def _run(coroutine):
    return asyncio.run(coroutine)


def _message(text=None, document=None, caption=None):
    return SimpleNamespace(chat_id=100, text=text, document=document, caption=caption)


class TestHandlers:
    def test_start_creates_service_and_scheduler(self, app):
        application, _ = app
        _run(application.post_init(application))
        assert FakeService.instances[0].calls == [("scheduler",)]

    def test_text_goes_to_service(self, app):
        _, handlers = app
        update = SimpleNamespace(effective_message=_message("привет"),
                                 effective_user=SimpleNamespace(id=7))
        _run(handlers["on_text"](update, None))
        assert ("text", 100, 7, "привет") in FakeService.instances[0].calls

    def test_text_without_sender_is_denied(self, app):
        _, handlers = app
        update = SimpleNamespace(effective_message=_message("привет"), effective_user=None)
        _run(handlers["on_text"](update, None))
        assert ("deny", 100, None) in FakeService.instances[0].calls

    def test_message_without_text_is_ignored(self, app):
        _, handlers = app
        update = SimpleNamespace(effective_message=_message(None),
                                 effective_user=SimpleNamespace(id=7))
        _run(handlers["on_text"](update, None))
        assert FakeService.instances == []

    def test_document_from_stranger_is_denied(self, app):
        _, handlers = app
        update = SimpleNamespace(effective_message=_message(document=object()),
                                 effective_user=SimpleNamespace(id=8))
        _run(handlers["on_document"](update, None))
        assert FakeService.instances[0].calls[-1] == ("deny", 100, 8)

    def test_document_without_sender_is_denied(self, app):
        _, handlers = app
        update = SimpleNamespace(effective_message=_message(document=object()),
                                 effective_user=None)
        _run(handlers["on_document"](update, None))
        assert FakeService.instances[0].calls[-1] == ("deny", 100, None)

    def test_update_without_document_or_query_is_ignored(self, app):
        _, handlers = app
        update = SimpleNamespace(effective_message=_message(), effective_user=None,
                                 callback_query=None)
        _run(handlers["on_document"](update, None))
        _run(handlers["on_button"](update, None))
        assert FakeService.instances == []

    def test_document_is_downloaded(self, app):
        _, handlers = app

        class File:
            async def download_as_bytearray(self):
                return bytearray(b"data")

        class Document:
            file_name = None

            async def get_file(self):
                return File()

        update = SimpleNamespace(
            effective_message=_message(document=Document(), caption="разбери"),
            effective_user=SimpleNamespace(id=7),
        )
        _run(handlers["on_document"](update, None))
        assert FakeService.instances[0].calls[-1] == (
            "document", 100, 7, "file", b"data", "разбери"
        )

    def test_button_resolves_approval(self, app):
        _, handlers = app
        events = []

        class Query:
            data = "approve:1:yes"
            from_user = SimpleNamespace(id=7)

            async def answer(self, text):
                events.append(("answer", text))

            async def edit_message_reply_markup(self, markup):
                events.append(("markup", markup))

        _run(handlers["on_button"](SimpleNamespace(callback_query=Query()), None))
        assert FakeService.instances[0].calls[-1] == ("approval", "approve:1:yes", 7)
        assert events == [("answer", "Принято"), ("markup", None)]


class TestRun:
    @pytest.fixture
    def settings(self, monkeypatch, tmp_path):
        s = bot_module.settings
        monkeypatch.setattr(s, "telegram_token", "123:ABC")
        monkeypatch.setattr(s, "telegram_allowed_ids", "7")
        monkeypatch.setattr(s, "workspace_dir", str(tmp_path / "ws"))
        return s

    def test_needs_token(self, settings, monkeypatch, capsys):
        monkeypatch.setattr(settings, "telegram_token", "")
        assert bot_module.run() == 1
        assert "TELEGRAM_BOT_TOKEN" in capsys.readouterr().out

    def test_bad_ids(self, settings, monkeypatch, capsys):
        monkeypatch.setattr(settings, "telegram_allowed_ids", "7,abc")
        assert bot_module.run() == 1
        assert "Некорректный Telegram ID" in capsys.readouterr().out

    def test_needs_allowed_ids(self, settings, monkeypatch, capsys):
        monkeypatch.setattr(settings, "telegram_allowed_ids", "")
        assert bot_module.run() == 1
        assert "PRIZOLOV_TELEGRAM_ALLOWED_IDS" in capsys.readouterr().out

    def test_starts_polling(self, settings, monkeypatch, capsys, tmp_path):
        started = []

        def fake_build(token, allowed, workspace):
            started.append((token, allowed, workspace))
            return SimpleNamespace(run_polling=lambda: started.append("polling"))

        monkeypatch.setattr(bot_module, "build_application", fake_build)
        assert bot_module.run() == 0
        assert started[0][:2] == ("123:ABC", {7})
        assert started[0][2].is_dir() and started[1] == "polling"
        assert "Бот запущен" in capsys.readouterr().out
