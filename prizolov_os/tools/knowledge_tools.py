# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Инструмент поиска по базе знаний пользователя."""

from ..knowledge import KnowledgeBase
from .base import Tool, make_schema


def knowledge_tool(knowledge: KnowledgeBase) -> Tool:
    def search_knowledge(query: str) -> str:
        hits = knowledge.search(query)
        if not hits:
            return (
                "В документах пользователя ничего не найдено. Попробуй другие слова "
                "(синонимы, ключевые термины) или другой источник."
            )
        blocks = [f"[{i}] {hit.source}\n{hit.text}" for i, hit in enumerate(hits, start=1)]
        return (
            "Фрагменты документов пользователя (самые подходящие сверху). Ссылайся на "
            "источник в скобках, например (договор.pdf, стр. 3).\n\n" + "\n\n".join(blocks)
        )

    return Tool(
        name="search_knowledge",
        description=(
            "Ищет по документам пользователя в рабочей папке (PDF, Word, Excel, txt, md, "
            "csv) и возвращает подходящие фрагменты с указанием файла и страницы или листа. "
            "Поиск по словам: формулируй запрос ключевыми терминами; если ничего не нашлось, "
            "попробуй синонимы. Используй, когда ответ может быть в документах пользователя."
        ),
        input_schema=make_schema({"query": {"type": "string", "description": "Ключевые слова"}}),
        handler=search_knowledge,
        untrusted=True,
    )
