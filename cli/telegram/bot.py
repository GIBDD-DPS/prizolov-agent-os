# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Запуск Telegram-бота на python-telegram-bot."""

import asyncio
import logging
from pathlib import Path
from typing import Any, List, Set, Tuple

from prizolov_os.config import settings
from prizolov_os.core.kernel import Kernel

from .service import TelegramService

logger = logging.getLogger(__name__)
SEND_TIMEOUT = 60


class PTBIO:
    """BotIO поверх python-telegram-bot: вызывается из рабочих потоков."""

    def __init__(self, bot: Any, loop: asyncio.AbstractEventLoop) -> None:
        self.bot = bot
        self.loop = loop

    def _call(self, coroutine: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(SEND_TIMEOUT)

    def send_text(self, chat_id: int, text: str, html: bool = False) -> int:
        from telegram.error import BadRequest

        try:
            message = self._call(self.bot.send_message(
                chat_id, text, parse_mode="HTML" if html else None
            ))
        except BadRequest:
            if not html:
                raise
            # Модель могла вернуть разметку, которую Telegram не принимает: шлём текстом.
            message = self._call(self.bot.send_message(chat_id, _strip_tags(text)))
        return int(message.message_id)

    def edit_text(self, chat_id: int, message_id: int, text: str) -> None:
        self._call(self.bot.edit_message_text(text, chat_id=chat_id, message_id=message_id))

    def send_buttons(self, chat_id: int, text: str, buttons: List[Tuple[str, str]]) -> int:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(label, callback_data=data) for label, data in buttons]]
        )
        message = self._call(self.bot.send_message(chat_id, text, reply_markup=markup))
        return int(message.message_id)

    def send_photo(self, chat_id: int, path: Path, caption: str = "") -> None:
        with open(path, "rb") as photo:
            self._call(self.bot.send_photo(chat_id, photo, caption=caption[:1000]))


def _strip_tags(text: str) -> str:
    import html
    import re

    return html.unescape(re.sub(r"<[^>]+>", "", text))


def build_application(token: str, allowed_ids: Set[int], workspace_dir: Path) -> Any:
    """Собирает приложение бота. Сетевых запросов не делает до запуска."""
    from telegram import Update
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )

    # concurrent_updates: пока агент работает, бот должен принимать нажатия кнопок.
    application = Application.builder().token(token).concurrent_updates(True).build()
    holder: dict = {}

    def service() -> TelegramService:
        if "service" not in holder:
            io = PTBIO(application.bot, asyncio.get_running_loop())
            holder["service"] = TelegramService(
                io, Kernel.create, allowed_ids, workspace_dir
            )
            holder["scheduler"] = holder["service"].start_scheduler()
        svc: TelegramService = holder["service"]
        return svc

    async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or message.text is None:
            return
        svc = service()
        if user is None:
            await asyncio.to_thread(svc.deny, message.chat_id, None)
            return
        await asyncio.to_thread(svc.handle_text, message.chat_id, user.id, message.text)

    async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or message.document is None:
            return
        svc = service()
        if user is None or not svc.is_allowed(user.id):
            await asyncio.to_thread(svc.deny, message.chat_id, user.id if user else None)
            return
        document = message.document
        file = await document.get_file()
        data = bytes(await file.download_as_bytearray())
        await asyncio.to_thread(
            svc.handle_document, message.chat_id, user.id, document.file_name or "file",
            data, message.caption or "",
        )

    async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        answer = service().resolve_approval(query.data or "", query.from_user.id)
        await query.answer(answer)
        await query.edit_message_reply_markup(None)

    async def on_start(app: Any) -> None:
        service()  # создаёт сервис и запускает планировщик сразу при старте бота

    application.post_init = on_start
    application.add_handler(MessageHandler(filters.Document.ALL, on_document))
    application.add_handler(MessageHandler(filters.TEXT, on_text))
    application.add_handler(CallbackQueryHandler(on_button, pattern=r"^approve:"))
    return application


def parse_allowed_ids(value: str) -> Set[int]:
    ids = set()
    for part in value.replace(";", ",").split(","):
        part = part.strip()
        if part:
            try:
                ids.add(int(part))
            except ValueError:
                raise ValueError(f"Некорректный Telegram ID: '{part}'") from None
    return ids


def run() -> int:
    """Точка входа `prizolov telegram`."""
    try:
        import telegram  # noqa: F401
    except ImportError:
        print('Нужна библиотека бота: pip install "prizolov-os[telegram]"')
        return 1
    if not settings.telegram_token:
        print("Не задан TELEGRAM_BOT_TOKEN в .env (токен выдаёт @BotFather)")
        return 1
    try:
        allowed = parse_allowed_ids(settings.telegram_allowed_ids)
    except ValueError as e:
        print(e)
        return 1
    if not allowed:
        print(
            "Не задан PRIZOLOV_TELEGRAM_ALLOWED_IDS - список Telegram ID, которым можно "
            "пользоваться ботом. Без него бот не запускается: иначе любой мог бы тратить "
            "ваш бюджет и читать ваши документы. Свой ID можно узнать у @userinfobot."
        )
        return 1
    workspace = Path(settings.workspace_dir)
    workspace.mkdir(parents=True, exist_ok=True)
    print(f"Бот запущен. Доступ: {', '.join(map(str, sorted(allowed)))}. Ctrl+C - остановить.")
    build_application(settings.telegram_token, allowed, workspace).run_polling()
    return 0
