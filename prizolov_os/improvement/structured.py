"""Запрос к модели со структурированным (JSON) ответом."""

import json
import logging
from typing import Any, Dict, Optional, Tuple

from ..llm import LLMClient, Usage

logger = logging.getLogger(__name__)


def ask_json(
    llm: LLMClient, system: str, prompt: str, schema: Dict[str, Any], max_tokens: int = 4000
) -> Tuple[Optional[Dict[str, Any]], Usage]:
    """Возвращает JSON по схеме или None, если модель отказалась или ответ не разобрать."""
    response = llm.complete(
        system=system,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        output_schema=schema,
    )
    if response.refused:
        logger.warning("Structured request refused")
        return None, response.usage
    try:
        data = json.loads(response.text)
    except json.JSONDecodeError:
        logger.warning("Structured response is not valid JSON: %.200s", response.text)
        return None, response.usage
    return (data if isinstance(data, dict) else None), response.usage


def object_schema(properties: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
