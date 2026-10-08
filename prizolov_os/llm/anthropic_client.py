# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""LLM-клиент на официальном SDK Anthropic."""

import logging
from typing import Any, Dict, List, Optional

import anthropic

from .base import LLMError, LLMResponse, Usage

logger = logging.getLogger(__name__)

# Если классификатор безопасности отклонит запрос, API сам повторит его
# на модели, которую Anthropic рекомендует для этой категории отказа.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Сжатие длинной истории на сервере.
COMPACTION_BETA = "compact-2026-01-12"
MIN_COMPACT_TRIGGER = 50_000


class AnthropicClient:
    """Клиент Claude: адаптивное мышление, кэширование промпта, fallback при отказе."""

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        effort: str = "medium",
        max_tokens: int = 16000,
        max_retries: int = 2,
        client: Optional[Any] = None,
        compact_trigger: int = 150_000,
    ) -> None:
        self.model = model
        # Порог сжатия в токенах; API не принимает меньше 50 000.
        self.compact_trigger = max(compact_trigger, MIN_COMPACT_TRIGGER)
        self.effort = effort
        self.max_tokens = max_tokens
        # Без api_key SDK сам найдёт ANTHROPIC_API_KEY или профиль `ant auth login`.
        self._client = client or anthropic.Anthropic(
            api_key=api_key, max_retries=max_retries
        )

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
        params: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "system": system,
            "messages": messages,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.effort},
            "cache_control": {"type": "ephemeral"},
            "betas": [FALLBACK_BETA],
            "fallbacks": "default",
        }
        if tools:
            params["tools"] = tools
        if compact:
            params["betas"] = [FALLBACK_BETA, COMPACTION_BETA]
            params["context_management"] = {"edits": [{
                "type": "compact_20260112",
                "trigger": {"type": "input_tokens", "value": self.compact_trigger},
            }]}
        if output_schema:
            params["output_config"] = {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": output_schema},
            }

        try:
            response = self._client.beta.messages.create(**params)
        except anthropic.AuthenticationError as e:
            raise LLMError("Неверный API-ключ Anthropic (ANTHROPIC_API_KEY)") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Превышен лимит запросов к Anthropic API") from e
        except anthropic.BadRequestError as e:
            raise LLMError(f"Некорректный запрос к Anthropic API: {e.message}") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Ошибка Anthropic API ({e.status_code}): {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError("Нет соединения с Anthropic API") from e
        except TypeError as e:
            # Так SDK сообщает, что не нашёл ни ключа, ни другого способа авторизации.
            if "authentication" not in str(e):
                raise
            raise LLMError(
                "Не задан ключ Anthropic: добавьте ANTHROPIC_API_KEY в .env"
            ) from e

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            logger.warning("Model refused: category=%s", getattr(details, "category", None))

        return LLMResponse(
            content=[
                block.model_dump(mode="json", by_alias=True, exclude_none=True)
                for block in response.content
                # Блок fallback - только служебная отметка о смене модели.
                if block.type != "fallback"
            ],
            stop_reason=response.stop_reason or "",
            model=response.model,
            usage=_usage(response.usage),
        )


def _usage(usage: Any) -> Usage:
    """Расход токенов. Если запрос шёл в несколько шагов (сжатие истории, запасная
    модель), верхние цифры относятся только к последнему шагу, а полный расход -
    сумма по usage.iterations."""
    parts = getattr(usage, "iterations", None) or [usage]

    def total(field: str) -> int:
        return sum(getattr(part, field, 0) or 0 for part in parts)

    return Usage(
        input_tokens=total("input_tokens"),
        output_tokens=total("output_tokens"),
        cache_read_input_tokens=total("cache_read_input_tokens"),
        cache_creation_input_tokens=total("cache_creation_input_tokens"),
        web_search_requests=getattr(
            getattr(usage, "server_tool_use", None), "web_search_requests", 0
        ) or 0,
    )
