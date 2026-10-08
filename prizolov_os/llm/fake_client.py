# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Офлайн-заглушка LLM для тестов и демонстраций без API-ключа."""

from typing import Any, Dict, List, Optional, Union

from .base import LLMResponse

Scripted = Union[str, LLMResponse]


def text_response(text: str) -> LLMResponse:
    """Ответ модели обычным текстом."""
    return LLMResponse(
        content=[{"type": "text", "text": text}], stop_reason="end_turn", model="fake"
    )


def tool_use_response(
    name: str, tool_input: Dict[str, Any], tool_id: str = "toolu_1", text: str = ""
) -> LLMResponse:
    """Ответ модели с вызовом инструмента."""
    content: List[Dict[str, Any]] = []
    if text:
        content.append({"type": "text", "text": text})
    content.append({"type": "tool_use", "id": tool_id, "name": name, "input": tool_input})
    return LLMResponse(content=content, stop_reason="tool_use", model="fake")


class FakeLLMClient:
    """Возвращает заранее заданные ответы по очереди и запоминает все запросы.

    Строка в сценарии превращается в текстовый ответ. Когда сценарий
    закончился, клиент отвечает эхом последнего сообщения пользователя.
    """

    def __init__(self, responses: Optional[List[Scripted]] = None) -> None:
        self._responses = list(responses or [])
        self.calls: List[Dict[str, Any]] = []

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
        self.calls.append(
            {
                "system": system,
                "messages": list(messages),
                "tools": tools,
                "max_tokens": max_tokens,
                "output_schema": output_schema,
                "compact": compact,
            }
        )
        if self._responses:
            item = self._responses.pop(0)
            return text_response(item) if isinstance(item, str) else item
        return text_response(f"[fake] {_last_user_text(messages)}")


def _last_user_text(messages: List[Dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        return " ".join(b.get("text", "") for b in content if b.get("type") == "text")
    return ""
