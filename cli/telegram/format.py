# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Оформление текста для Telegram: Markdown модели -> HTML Telegram, деление длинных ответов."""

import html
import re
from typing import List

from rich.text import Text

from prizolov_os.events import Event

from ..render import progress_markup

MAX_MESSAGE = 4000  # у Telegram лимит 4096 символов


def to_telegram_html(markdown: str) -> str:
    """Упрощённый перевод Markdown в HTML, который понимает Telegram."""
    blocks = re.split(r"(```.*?```)", markdown, flags=re.S)
    out = []
    for block in blocks:
        if block.startswith("```") and block.endswith("```"):
            code = block[3:-3].split("\n", 1)[-1] if "\n" in block else block[3:-3]
            out.append(f"<pre>{html.escape(code.strip())}</pre>")
            continue
        text = html.escape(block, quote=False)
        text = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", text, flags=re.M)
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
        text = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<i>\1</i>", text)
        text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
        text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', text)
        text = re.sub(r"^\s*[-*]\s+", "• ", text, flags=re.M)
        out.append(text)
    return "".join(out)


def split_message(text: str, limit: int = MAX_MESSAGE) -> List[str]:
    """Делит длинный текст по абзацам и строкам, не разрывая слова."""
    parts: List[str] = []
    while len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts or [""]


def progress_line(event: Event) -> str:
    """Строка прогресса без разметки (та же, что в CLI)."""
    markup = progress_markup(event)
    return Text.from_markup(markup).plain.strip() if markup else ""
