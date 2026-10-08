# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Встроенные инструменты: калькулятор, дата и время, файлы в рабочей папке."""

import ast
import math
import operator
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..__about__ import SIGNATURE
from ..config import settings
from .base import ServerTool, Tool, make_schema

MAX_READ_BYTES = 200_000
MAX_POWER = 1000
MAX_RESULT_DIGITS = 10_000

_BINARY_OPS: Dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: Dict[type, Callable[[Any], Any]] = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCTIONS: Dict[str, Callable[..., Any]] = {
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
}
_CONSTANTS = {"pi": math.pi, "e": math.e}

Number = Union[int, float]


def calculate(expression: str) -> str:
    """Безопасно вычисляет арифметическое выражение (без eval)."""
    tree = ast.parse(expression.replace("^", "**"), mode="eval")
    return str(_evaluate(tree.body))


def _evaluate(node: ast.AST) -> Number:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPS:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow):
            if abs(right) > MAX_POWER:
                raise ValueError(f"Слишком большая степень (больше {MAX_POWER})")
            if abs(left) > 1 and right * math.log10(abs(left)) > MAX_RESULT_DIGITS:
                raise ValueError("Слишком большой результат")
        return _BINARY_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_evaluate(node.operand))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FUNCTIONS
        and not node.keywords
    ):
        return _FUNCTIONS[node.func.id](*(_evaluate(arg) for arg in node.args))
    raise ValueError("Допустимы только числа, + - * / // % **, скобки, pi, e и функции: "
                     + ", ".join(_FUNCTIONS))


def current_datetime(timezone: str) -> str:
    """Текущие дата и время в указанном часовом поясе."""
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Неизвестный часовой пояс '{timezone}'") from None
    now = datetime.now(zone)
    return now.strftime("%Y-%m-%d %H:%M:%S %Z (%A)")


def calculator_tool() -> Tool:
    return Tool(
        name="calculator",
        description=(
            "Вычисляет арифметическое выражение и возвращает число. Используй для любых "
            "расчётов вместо подсчёта в уме. Поддерживает + - * / // % ** (или ^), скобки, "
            "pi, e и функции sqrt, log, log10, exp, sin, cos, tan, abs, round, min, max."
        ),
        input_schema=make_schema(
            {"expression": {"type": "string", "description": "Например: (1500 * 1.12) / 3"}}
        ),
        handler=calculate,
    )


def datetime_tool() -> Tool:
    return Tool(
        name="current_datetime",
        description=(
            "Возвращает текущие дату, время и день недели. Вызывай, когда ответ зависит "
            "от сегодняшней даты."
        ),
        input_schema=make_schema(
            {"timezone": {"type": "string", "description": "IANA-пояс, например Europe/Moscow"}}
        ),
        handler=current_datetime,
    )


SIGNED_SUFFIXES = {".md": "\n\n---\n_{}_\n", ".txt": "\n\n---\n{}\n", ".html": "\n<!-- {} -->\n"}


def sign(path: Path, content: str) -> str:
    """Добавляет подпись авторства в текстовый документ (один раз)."""
    template = SIGNED_SUFFIXES.get(path.suffix.lower())
    if template is None or SIGNATURE in content:
        return content
    return content.rstrip("\n") + template.format(SIGNATURE)


class Workspace:
    """Рабочая папка агента. Пути за её пределами запрещены."""

    def __init__(self, root: Union[str, Path], sign_output: Optional[bool] = None) -> None:
        self.root = Path(root).resolve()
        self.sign_output = settings.sign_output if sign_output is None else sign_output

    def resolve(self, path: str) -> Path:
        target = (self.root / path).resolve()
        if target != self.root and not target.is_relative_to(self.root):
            raise PermissionError(f"Путь '{path}' выходит за пределы рабочей папки")
        return target

    def list_files(self, path: str) -> str:
        directory = self.resolve(path)
        if not directory.is_dir():
            raise FileNotFoundError(f"Папка '{path}' не найдена")
        entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name))
        lines = [
            f"{p.relative_to(self.root)}/" if p.is_dir()
            else f"{p.relative_to(self.root)} ({p.stat().st_size} байт)"
            for p in entries
        ]
        return "\n".join(lines) or "(папка пуста)"

    def read_file(self, path: str) -> str:
        file = self.resolve(path)
        if not file.is_file():
            raise FileNotFoundError(f"Файл '{path}' не найден")
        data = file.read_bytes()
        text = data[:MAX_READ_BYTES].decode("utf-8", errors="replace")
        if len(data) > MAX_READ_BYTES:
            text += f"\n\n[Показаны первые {MAX_READ_BYTES} байт из {len(data)}]"
        return text

    def write_file(self, path: str, content: str) -> str:
        file = self.resolve(path)
        if file == self.root:
            raise IsADirectoryError("Укажите имя файла")
        file.parent.mkdir(parents=True, exist_ok=True)
        if self.sign_output:
            content = sign(file, content)
        file.write_text(content, encoding="utf-8")
        return f"Записано {len(content)} символов в {file.relative_to(self.root)}"


def file_tools(workspace: Workspace) -> List[Tool]:
    path_param = {"type": "string", "description": "Путь относительно рабочей папки"}
    return [
        Tool(
            name="list_files",
            description="Показывает файлы и папки в рабочей папке. Корень - '.'.",
            input_schema=make_schema({"path": path_param}),
            handler=workspace.list_files,
            untrusted=True,
        ),
        Tool(
            name="read_file",
            description="Читает текстовый файл из рабочей папки.",
            input_schema=make_schema({"path": path_param}),
            handler=workspace.read_file,
            untrusted=True,
        ),
        Tool(
            name="write_file",
            description=(
                "Создаёт или перезаписывает текстовый файл в рабочей папке. "
                "Перед записью человек подтверждает действие."
            ),
            input_schema=make_schema(
                {"path": path_param, "content": {"type": "string", "description": "Текст"}}
            ),
            handler=workspace.write_file,
            requires_approval=True,
        ),
    ]


def default_tools(workspace_dir: Union[str, Path]) -> List[Tool]:
    """Базовый набор: калькулятор, дата и время, файлы."""
    return [calculator_tool(), datetime_tool(), *file_tools(Workspace(workspace_dir))]


def web_search_tool(max_uses: int = 5) -> ServerTool:
    """Веб-поиск на серверах Anthropic (оплачивается за каждый поиск)."""
    return ServerTool(
        "web_search", {"type": "web_search_20260209", "name": "web_search", "max_uses": max_uses}
    )


def web_fetch_tool(max_uses: int = 5) -> ServerTool:
    """Чтение веб-страниц по ссылкам, которые уже есть в диалоге."""
    return ServerTool(
        "web_fetch", {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": max_uses}
    )
