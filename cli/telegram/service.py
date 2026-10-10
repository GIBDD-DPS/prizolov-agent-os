# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Логика Telegram-бота, независимая от библиотеки Telegram.

Бот общается с Telegram через BotIO (отправить, изменить сообщение, кнопки, фото).
Работа агента идёт в отдельном потоке; подтверждения ждут нажатия кнопки.
"""

import html
import io
import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Set, Tuple

from rich.console import Console

from prizolov_os import events as ev
from prizolov_os.__about__ import HEADER
from prizolov_os.core.kernel import Kernel
from prizolov_os.events import Event
from prizolov_os.llm import LLMError

from ..app import ChatApp
from ..render import format_params, format_usd, short
from .format import progress_line, split_message, to_telegram_html

logger = logging.getLogger(__name__)

APPROVAL_TIMEOUT = 300.0
MAX_STATUS = 3500
PROGRESS_INTERVAL = 1.5
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
INBOX = "inbox"
UPLOAD_SUFFIXES = {".pdf", ".docx", ".xlsx", ".xlsm", ".csv", ".txt", ".md"}
# Команды чата, которые безопасно выполнять из Telegram. Подтверждения изменений
# (одобрить инструмент, промпт, сбросить калибровку) - только в CLI.
ALLOWED_COMMANDS = {
    "/new", "/sessions", "/status", "/log", "/cost", "/budget", "/good", "/bad",
    "/lessons", "/facts", "/forecasts", "/verify", "/quality", "/index", "/prompts",
    "/tools", "/improve", "/schedule",
}
HELP = (
    f"{HEADER}\n\n"
    "Пишите задачу обычным сообщением или пришлите документ (PDF, Word, Excel, CSV) - "
    "он попадёт в базу знаний.\n\n"
    "Команды: /new - новый диалог, /good и /bad комментарий - оценка ответа, "
    "/cost - расходы, /forecasts - точность прогнозов, /verify - сверить прогнозы, "
    "/quality - качество, /facts, /lessons, /status, /index.\n"
    "Расписание: /schedule; например /schedule report \"по будням 9:00\" GOLD 1,7,15,30 "
    "или просто попросите «присылай каждое утро обзор золота».\n"
    "Одобрение инструментов и промптов, сброс калибровки - в CLI (prizolov chat)."
)


class BotIO(Protocol):
    """Действия в Telegram. Методы вызываются из рабочих потоков."""

    def send_text(self, chat_id: int, text: str, html: bool = False) -> int: ...

    def edit_text(self, chat_id: int, message_id: int, text: str) -> None: ...

    def send_buttons(
        self, chat_id: int, text: str, buttons: List[Tuple[str, str]]
    ) -> int: ...

    def send_photo(self, chat_id: int, path: Path, caption: str = "") -> None: ...


KernelFactory = Callable[..., Kernel]


@dataclass
class _Approval:
    chat_id: int
    event: threading.Event = field(default_factory=threading.Event)
    allowed: bool = False


@dataclass
class _Chat:
    kernel: Kernel
    busy: threading.Lock = field(default_factory=threading.Lock)
    notes: List[str] = field(default_factory=list)


class TelegramService:
    def __init__(
        self,
        io: BotIO,
        kernel_factory: KernelFactory,
        allowed_ids: Set[int],
        workspace_dir: Path,
        approval_timeout: float = APPROVAL_TIMEOUT,
    ) -> None:
        self.io = io
        self.kernel_factory = kernel_factory
        self.allowed_ids = set(allowed_ids)
        self.workspace_dir = Path(workspace_dir)
        self.approval_timeout = approval_timeout
        self._chats: Dict[int, _Chat] = {}
        self._approvals: Dict[str, _Approval] = {}
        self._lock = threading.Lock()

    # --- Доступ --------------------------------------------------------------

    def is_allowed(self, user_id: Optional[int]) -> bool:
        return user_id is not None and user_id in self.allowed_ids

    def deny(self, chat_id: int, user_id: Optional[int]) -> None:
        logger.warning("Telegram: access denied for user %s", user_id)
        self.io.send_text(
            chat_id, f"Доступ запрещён. Ваш Telegram ID: {user_id}. Попросите владельца "
            "добавить его в PRIZOLOV_TELEGRAM_ALLOWED_IDS."
        )

    # --- Сообщения -----------------------------------------------------------

    def handle_text(self, chat_id: int, user_id: int, text: str) -> None:
        if not self.is_allowed(user_id):
            return self.deny(chat_id, user_id)
        text = text.strip()
        if not text:
            return
        if text.startswith("/"):
            return self.handle_command(chat_id, user_id, text)
        chat = self._chat(chat_id)
        if not chat.busy.acquire(blocking=False):
            self.io.send_text(chat_id, "Ещё работаю над предыдущей задачей, подождите.")
            return
        try:
            self._run_task(chat_id, chat, text)
        finally:
            chat.busy.release()

    def _run_task(self, chat_id: int, chat: _Chat, text: str) -> None:
        if chat.notes:
            text = "\n".join(chat.notes) + "\n\n" + text
            chat.notes.clear()
        status = self.io.send_text(chat_id, "⏳ Думаю…")
        progress = _Progress(self.io, chat_id, status)
        unsubscribe = chat.kernel.events.subscribe(progress.on_event)
        try:
            result = chat.kernel.chat(text)
        except LLMError as e:
            progress.finish(f"⚠ {e}")
            return
        except Exception as e:  # noqa: BLE001 - пользователь должен узнать о сбое
            logger.exception("Telegram task failed")
            progress.finish(f"⚠ Ошибка: {e}")
            return
        finally:
            unsubscribe()
        usage = result.usage
        progress.finish(
            f"✓ Готово · вход {usage.input_tokens}, выход {usage.output_tokens} · "
            f"{format_usd(usage.cost_usd)}"
        )
        for part in split_message(result.text or "(пустой ответ)"):
            self.io.send_text(chat_id, to_telegram_html(part), html=True)
        for chart in progress.charts:
            path = self.workspace_dir / chart
            if path.is_file():
                self.io.send_photo(chat_id, path, caption=chart)

    def handle_command(self, chat_id: int, user_id: int, text: str) -> None:
        if not self.is_allowed(user_id):
            return self.deny(chat_id, user_id)
        name = text.split()[0].split("@")[0]
        if name in ("/start", "/help"):
            self.io.send_text(chat_id, HELP)
            return
        if name not in ALLOWED_COMMANDS:
            self.io.send_text(chat_id, "Эта команда доступна только в CLI (prizolov chat).")
            return
        out = io.StringIO()
        app = ChatApp(
            self._chat(chat_id).kernel,
            Console(file=out, width=70, color_system=None),
            lambda _: "",  # подтверждения из Telegram не принимаются
        )
        app.handle(name + text[len(text.split()[0]):])
        output = out.getvalue().strip() or "Готово."
        for part in split_message(output, 3500):
            self.io.send_text(chat_id, f"<pre>{_escape(part)}</pre>", html=True)

    def handle_document(
        self, chat_id: int, user_id: int, filename: str, data: bytes, caption: str = ""
    ) -> None:
        if not self.is_allowed(user_id):
            return self.deny(chat_id, user_id)
        name = _safe_name(filename)
        if Path(name).suffix.lower() not in UPLOAD_SUFFIXES:
            self.io.send_text(
                chat_id, "Поддерживаются PDF, Word (.docx), Excel (.xlsx), CSV, TXT и MD."
            )
            return
        if len(data) > MAX_UPLOAD_BYTES:
            self.io.send_text(chat_id, "Файл больше 20 МБ.")
            return
        target = _unique(self.workspace_dir / INBOX / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        relative = target.relative_to(self.workspace_dir).as_posix()
        chat = self._chat(chat_id)
        if chat.kernel.knowledge is not None:
            chat.kernel.knowledge.index()
        note = f"[Пользователь прислал файл: {relative}]"
        if caption.strip():
            chat.notes.append(note)
            self.handle_text(chat_id, user_id, caption)
        else:
            chat.notes.append(note)
            self.io.send_text(
                chat_id, f"Файл сохранён: {relative} и добавлен в базу знаний. "
                "Что с ним сделать?"
            )

    # --- Расписание ----------------------------------------------------------

    def notify(self, chat_id: int, text: str, files: Sequence[Path]) -> None:
        """Доставка результата задачи по расписанию в чат."""
        for part in split_message(text):
            self.io.send_text(chat_id, to_telegram_html(part), html=True)
        for path in files:
            if Path(path).is_file():
                self.io.send_photo(chat_id, Path(path), caption=Path(path).name)

    def start_scheduler(self, interval: float = 30.0) -> Any:
        """Запускает планировщик в фоне (одним процессом с ботом)."""
        from prizolov_os.scheduler import ScheduleRunner

        kernel = self.kernel_factory(workspace_dir=self.workspace_dir)
        kernel.schedules.ensure_builtin()
        return ScheduleRunner(kernel, notifier=self.notify).start_background(interval)

    # --- Подтверждения -------------------------------------------------------

    def approver_for(self, chat_id: int) -> Callable[[str, Dict[str, Any]], bool]:
        def approve(tool: str, params: Dict[str, Any]) -> bool:
            approval_id = uuid.uuid4().hex[:12]
            approval = _Approval(chat_id)
            with self._lock:
                self._approvals[approval_id] = approval
            if tool == "write_file":
                preview = short(str(params.get("content", "")), 300)
                text = f"Агент хочет записать файл {params.get('path')}:\n\n{preview}"
            else:
                text = f"Агент хочет выполнить {tool}({format_params(params)})"
            self.io.send_buttons(chat_id, text, [
                ("✅ Разрешить", f"approve:{approval_id}:yes"),
                ("❌ Отклонить", f"approve:{approval_id}:no"),
            ])
            answered = approval.event.wait(self.approval_timeout)
            with self._lock:
                self._approvals.pop(approval_id, None)
            if not answered:
                self.io.send_text(chat_id, "Нет ответа 5 минут - действие отклонено.")
            return answered and approval.allowed

        return approve

    def resolve_approval(self, data: str, user_id: int) -> str:
        """Обработка нажатия кнопки. Возвращает текст-ответ на нажатие."""
        if not self.is_allowed(user_id):
            return "Доступ запрещён"
        match = re.fullmatch(r"approve:([0-9a-f]+):(yes|no)", data)
        if not match:
            return "Неизвестная кнопка"
        with self._lock:
            approval = self._approvals.get(match.group(1))
        if approval is None:
            return "Запрос уже неактуален"
        approval.allowed = match.group(2) == "yes"
        approval.event.set()
        return "Разрешено" if approval.allowed else "Отклонено"

    # --- Диалоги -------------------------------------------------------------

    def _chat(self, chat_id: int) -> _Chat:
        with self._lock:
            chat = self._chats.get(chat_id)
            if chat is None:
                session_id = f"tg-{chat_id}"
                kernel = self.kernel_factory(
                    approver=self.approver_for(chat_id), session_id=session_id,
                    workspace_dir=self.workspace_dir,
                )
                kernel.chat_id = chat_id
                if kernel.store.load_session(session_id) is not None:
                    kernel.resume(session_id)
                chat = self._chats[chat_id] = _Chat(kernel)
            return chat


class _Progress:
    """Одно сообщение о ходе работы, которое обновляется не чаще раза в 1.5 с."""

    def __init__(self, io: BotIO, chat_id: int, message_id: int) -> None:
        self.io, self.chat_id, self.message_id = io, chat_id, message_id
        self.lines: List[str] = []
        self.charts: List[str] = []
        self._last_edit = 0.0
        self._lock = threading.Lock()

    def on_event(self, event: Event) -> None:
        if event.type == ev.TOOL_RESULT and event.data.get("tool", "").startswith("chart_"):
            self._collect_charts(event.data.get("output", ""))
        line = progress_line(event)
        if not line:
            return
        with self._lock:
            self.lines.append(line)
            if time.monotonic() - self._last_edit < PROGRESS_INTERVAL:
                return
            self._last_edit = time.monotonic()
            text = "⏳ " + "\n".join(self.lines[-6:])
        self._edit(text)

    def finish(self, summary: str) -> None:
        with self._lock:
            text = "\n".join([*self.lines[-6:], summary])
        self._edit(text)

    def _edit(self, text: str) -> None:
        try:
            self.io.edit_text(self.chat_id, self.message_id, text[:MAX_STATUS])
        except Exception:  # noqa: BLE001 - прогресс не должен ломать задачу
            logger.debug("Progress edit failed", exc_info=True)

    def _collect_charts(self, output: str) -> None:
        try:
            data = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return
        charts = data.get("charts") or ([data["chart"]] if data.get("chart") else [])
        self.charts.extend(str(c) for c in charts)


def _escape(text: str) -> str:
    return html.escape(text, quote=False)


def _safe_name(filename: str) -> str:
    name = Path(filename or "file").name
    name = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE).strip("._") or "file"
    return name[:100]


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(2, 1000):
        candidate = path.with_name(f"{path.stem}-{i}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(path)


__all__ = ["BotIO", "TelegramService"]
