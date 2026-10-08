# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Общий интерфейс LLM-клиента.

Остальной код Prizolov OS зависит только от этого модуля, а не от SDK конкретного
провайдера. Блоки ответа хранятся как обычные dict: их можно сохранить в JSON
и без изменений отправить обратно модели в следующем запросе.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


class LLMError(Exception):
    """Ошибка обращения к LLM (сеть, авторизация, лимиты, неверный запрос)."""


@dataclass
class ToolCall:
    """Вызов инструмента, который запросила модель."""

    id: str
    name: str
    input: Dict[str, Any]


@dataclass
class Usage:
    """Расход токенов за один запрос."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    web_search_requests: int = 0
    cost_usd: float = 0.0


@dataclass
class LLMResponse:
    """Ответ модели.

    Attributes:
        content: Блоки ответа (text, tool_use, thinking, ...) в виде dict.
            Добавляйте их в историю целиком: {"role": "assistant", "content": content}.
        stop_reason: Причина остановки: end_turn, tool_use, max_tokens, refusal, ...
        model: Модель, которая фактически ответила.
        usage: Расход токенов.
    """

    content: List[Dict[str, Any]]
    stop_reason: str
    model: str
    usage: Usage = field(default_factory=Usage)

    @property
    def text(self) -> str:
        """Весь текст ответа одной строкой."""
        return "".join(b.get("text", "") for b in self.content if b.get("type") == "text")

    @property
    def tool_calls(self) -> List[ToolCall]:
        """Вызовы инструментов из ответа."""
        return [
            ToolCall(id=b["id"], name=b["name"], input=b.get("input") or {})
            for b in self.content
            if b.get("type") == "tool_use"
        ]

    @property
    def compacted(self) -> bool:
        """В ответе есть сжатое содержание старой части диалога."""
        return any(b.get("type") == "compaction" for b in self.content)

    @property
    def refused(self) -> bool:
        """Модель отказалась отвечать по соображениям безопасности."""
        return self.stop_reason == "refusal"


class LLMClient(Protocol):
    """Интерфейс, который реализует любой LLM-клиент."""

    def complete(
        self,
        *,
        system: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        compact: bool = False,
    ) -> LLMResponse:
        """Отправляет диалог модели и возвращает её ответ.

        output_schema - JSON Schema: модель обязана ответить JSON по этой схеме
        (текст ответа - валидный JSON).
        compact - разрешить сжатие длинной истории: когда она превысит порог, старая
        часть заменяется кратким содержанием (блок compaction в ответе).
        """
        ...
