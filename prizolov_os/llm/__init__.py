# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""LLM-слой Prizolov OS."""

from typing import Optional

from ..config import Settings, settings
from .anthropic_client import AnthropicClient
from .base import LLMClient, LLMError, LLMResponse, ToolCall, Usage
from .fake_client import FakeLLMClient, text_response, tool_use_response


def create_client(config: Optional[Settings] = None) -> LLMClient:
    """Создаёт LLM-клиент по настройкам (по умолчанию - глобальным)."""
    config = config or settings
    return AnthropicClient(
        model=config.model,
        api_key=config.api_key,
        effort=config.effort,
        max_tokens=config.max_tokens,
        compact_trigger=config.compact_at or 150_000,
        max_retries=config.max_retries,
    )


__all__ = [
    "AnthropicClient",
    "FakeLLMClient",
    "LLMClient",
    "LLMError",
    "LLMResponse",
    "ToolCall",
    "Usage",
    "create_client",
    "text_response",
    "tool_use_response",
]
