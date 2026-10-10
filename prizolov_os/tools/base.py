# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Инструменты агента: описание, проверка параметров и выполнение."""

import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union

from ..llm import ToolCall
from ..security import scan, wrap_untrusted

logger = logging.getLogger(__name__)

# Спрашивает у человека разрешение на вызов инструмента: (имя, параметры) -> да/нет.
Approver = Callable[[str, Dict[str, Any]], bool]


def serialized(approver: Optional[Approver]) -> Optional[Approver]:
    """Подтверждения по одному: несколько агентов могут спрашивать одновременно."""
    if approver is None:
        return None
    lock = threading.Lock()

    def ask(name: str, params: Dict[str, Any]) -> bool:
        with lock:
            return approver(name, params)

    return ask


class ToolInputError(ValueError):
    """Параметры вызова не соответствуют схеме инструмента."""


@dataclass
class Tool:
    """Инструмент, который модель может вызвать.

    Attributes:
        name: Имя для модели (латиница, цифры, _).
        description: Что делает инструмент и когда его вызывать.
        input_schema: JSON Schema параметров (type: object).
        handler: Функция, которая получает параметры как именованные аргументы.
        requires_approval: Перед вызовом спросить разрешение у человека.
        untrusted: Результат содержит внешние данные (файлы, выписки): он
            оборачивается в <untrusted_data> и проверяется на prompt-injection.
    """

    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[..., Any]
    requires_approval: bool = False
    untrusted: bool = False

    def to_api(self) -> Dict[str, Any]:
        """Описание инструмента в формате Messages API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "strict": True,
        }


@dataclass
class ServerTool:
    """Инструмент, который выполняют серверы Anthropic (веб-поиск, чтение страниц).

    Модель вызывает его сама, результат приходит в том же ответе,
    поэтому локально такой инструмент не выполняется.
    """

    name: str
    spec: Dict[str, Any]

    def to_api(self) -> Dict[str, Any]:
        return dict(self.spec)


AnyTool = Union[Tool, ServerTool]


@dataclass
class ToolResult:
    """Результат вызова инструмента."""

    tool_use_id: str
    name: str
    input: Dict[str, Any]
    output: str
    is_error: bool = False
    suspicious: List[str] = field(default_factory=list)

    def to_api(self) -> Dict[str, Any]:
        """Блок tool_result для следующего сообщения модели."""
        block: Dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": self.tool_use_id,
            "content": self.output,
        }
        if self.is_error:
            block["is_error"] = True
        return block


def make_schema(properties: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Схема объекта, в которой все параметры обязательны (так требует strict)."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_JSON_TYPES: Dict[str, Union[type, Tuple[type, ...]]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def validate_input(schema: Dict[str, Any], data: Any) -> None:
    """Проверяет параметры по схеме (типы, обязательные поля, enum, лишние поля)."""
    if not isinstance(data, dict):
        raise ToolInputError("Параметры должны быть объектом")
    properties = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in data:
            raise ToolInputError(f"Не указан обязательный параметр '{key}'")
    for key, value in data.items():
        if key not in properties:
            if schema.get("additionalProperties") is False:
                raise ToolInputError(f"Неизвестный параметр '{key}'")
            continue
        spec = properties[key]
        expected = _JSON_TYPES.get(spec.get("type", ""))
        # bool - подкласс int в Python, но в JSON это разные типы.
        wrong_bool = isinstance(value, bool) and spec.get("type") in ("integer", "number")
        if expected and (not isinstance(value, expected) or wrong_bool):
            raise ToolInputError(f"Параметр '{key}' должен иметь тип {spec['type']}")
        if "enum" in spec and value not in spec["enum"]:
            raise ToolInputError(f"Параметр '{key}' должен быть одним из {spec['enum']}")


class ToolRegistry:
    """Набор инструментов агента."""

    def __init__(self, tools: Iterable[AnyTool] = ()) -> None:
        self._tools: Dict[str, AnyTool] = {}
        for tool in tools:
            self.add(tool)

    def add(self, tool: AnyTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Инструмент '{tool.name}' уже зарегистрирован")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[AnyTool]:
        return self._tools.get(name)

    def names(self) -> List[str]:
        return list(self._tools)

    def schemas(self) -> List[Dict[str, Any]]:
        """Описания всех инструментов для запроса к модели."""
        return [tool.to_api() for tool in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def execute(self, call: ToolCall, approver: Optional[Approver] = None) -> ToolResult:
        """Выполняет вызов. Любая ошибка возвращается модели как is_error, а не бросается."""

        def error(message: str) -> ToolResult:
            logger.warning("Tool %s failed: %s", call.name, message)
            return ToolResult(call.id, call.name, call.input, f"Ошибка: {message}", True)

        tool = self._tools.get(call.name)
        if tool is None:
            return error(f"инструмент '{call.name}' не существует")
        if isinstance(tool, ServerTool):
            return error(f"инструмент '{call.name}' выполняется на сервере")
        try:
            validate_input(tool.input_schema, call.input)
        except ToolInputError as e:
            return error(str(e))
        if tool.requires_approval and not (approver and approver(call.name, call.input)):
            return error("пользователь не разрешил это действие")

        logger.info("Calling tool %s", call.name)
        try:
            output = tool.handler(**call.input)
        except Exception as e:  # noqa: BLE001 - ошибку инструмента должна увидеть модель
            return error(str(e) or type(e).__name__)
        if not isinstance(output, str):
            output = json.dumps(output, ensure_ascii=False, default=str)
        findings = scan(output)
        if tool.untrusted:
            source = call.name + (f":{call.input['path']}" if "path" in call.input else "")
            output = wrap_untrusted(output, source, findings)
        elif findings:
            output = wrap_untrusted(output, call.name, findings)
        if findings:
            logger.warning("Possible prompt injection in %s output", call.name)
        return ToolResult(
            call.id, call.name, call.input, output, suspicious=[f.snippet for f in findings]
        )
