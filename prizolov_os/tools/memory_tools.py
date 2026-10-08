# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Инструменты долговременной памяти: запомнить и вспомнить факт."""

from typing import List

from ..memory import Store
from .base import Tool, make_schema


def memory_tools(store: Store) -> List[Tool]:
    def remember(fact: str) -> str:
        fact_id = store.add_fact(fact)
        return f"Запомнено (#{fact_id})"

    def recall(query: str) -> str:
        facts = store.search_facts(query, limit=10)
        if not facts:
            return "В памяти ничего не найдено"
        return "\n".join(f"- {f.text}" for f in facts)

    return [
        Tool(
            name="remember",
            description=(
                "Сохраняет в долговременную память важный устойчивый факт о пользователе "
                "или его бизнесе (реквизиты, налоговый режим, предпочтения, цели). "
                "Не сохраняй разовые детали текущей задачи. Формулируй факт самодостаточно."
            ),
            input_schema=make_schema({"fact": {"type": "string"}}),
            handler=remember,
        ),
        Tool(
            name="recall",
            description=(
                "Ищет в долговременной памяти факты о пользователе и его бизнесе по "
                "ключевым словам. Вызывай, когда для ответа может пригодиться то, что "
                "пользователь сообщал раньше."
            ),
            input_schema=make_schema({"query": {"type": "string"}}),
            handler=recall,
        ),
    ]
