"""Инструменты, которые предлагают сами агенты.

Агент присылает описание, схему параметров и код на Python с функцией run(**params).
Инструмент подключается только после того, как человек прочитал код и подтвердил.

Защита (ни одна мера не заменяет проверку кода человеком):
1. Статическая проверка: только модули из белого списка, запрещены опасные
   встроенные функции и обращение к атрибутам с подчёркиванием.
2. Запуск в отдельном процессе Python (-I) с таймаутом, во временной папке,
   с пустым окружением и урезанными встроенными функциями; на Linux - с лимитами
   памяти и процессорного времени.
"""

import ast
import functools
import importlib
import json
import re
import subprocess
import sys
import tempfile
import types
from typing import Any, Callable, Dict, List

from ..memory import CustomToolRecord, Store
from ..tools import Tool, make_schema

ALLOWED_MODULES = {
    "math", "statistics", "datetime", "json", "re", "decimal", "fractions",
    "itertools", "functools", "collections", "string", "textwrap", "random",
    "calendar", "bisect", "heapq", "unicodedata",
}
FORBIDDEN_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "input", "breakpoint", "help", "memoryview",
    "exit", "quit", "type", "object", "super", "classmethod", "staticmethod", "property",
}
# Атрибуты, через которые можно добраться до кадров стека, кода и глобальных переменных.
FORBIDDEN_ATTR_PREFIXES = ("_", "gi_", "f_", "tb_", "cr_", "ag_", "co_", "func_")
FORBIDDEN_ATTRS = {"mro", "modules", "system", "popen", "loader", "spec"}
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
TIMEOUT_SECONDS = 10
MAX_OUTPUT_CHARS = 50_000

# Выполняется в отдельном процессе: читает {"code", "params"} из stdin.
RUNNER = r"""
import builtins, json, sys
try:
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
except Exception:
    pass
payload = json.loads(sys.stdin.read())
real_import = builtins.__import__
allowed = set(payload["allowed"])
def safe_import(name, *args, **kwargs):
    if name.split(".")[0] not in allowed:
        raise ImportError("module not allowed: " + name)
    return real_import(name, *args, **kwargs)
safe = {k: getattr(builtins, k) for k in dir(builtins)
        if not k.startswith("_") and k not in set(payload["forbidden"])}
safe["__import__"] = safe_import
scope = {"__builtins__": safe, "__name__": "custom_tool"}
exec(compile(payload["code"], "<custom_tool>", "exec"), scope)
result = scope["run"](**payload["params"])
sys.stdout.write(json.dumps({"result": result}, ensure_ascii=False, default=str))
"""


class UnsafeCodeError(ValueError):
    """Код инструмента не прошёл проверку безопасности."""


def check_code(code: str) -> None:
    """Проверяет код инструмента. Бросает UnsafeCodeError с причиной."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise UnsafeCodeError(f"Синтаксическая ошибка: {e}") from None

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _check_module(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise UnsafeCodeError("Относительные импорты запрещены")
            _check_module(node.module or "")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise UnsafeCodeError(f"Запрещено использовать '{node.id}'")
        elif isinstance(node, ast.Attribute) and _forbidden_attr(node.attr):
            raise UnsafeCodeError(f"Запрещено обращаться к атрибуту '{node.attr}'")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            raise UnsafeCodeError("global и nonlocal запрещены")

    if not any(isinstance(n, ast.FunctionDef) and n.name == "run" for n in tree.body):
        raise UnsafeCodeError("Код должен определять функцию run(**params) на верхнем уровне")


@functools.lru_cache(maxsize=1)
def _module_attrs() -> frozenset:
    """Имена атрибутов, через которые из разрешённых модулей виден другой модуль.

    Например, calendar.sys или re.enum: по ним можно дойти до sys и os.
    """
    names = {"sys", "os", "builtins", "subprocess", "importlib", "shutil", "socket"}
    seen: set = set()
    queue = [importlib.import_module(name) for name in ALLOWED_MODULES]
    while queue:
        module = queue.pop()
        if id(module) in seen:
            continue
        seen.add(id(module))
        for attr, value in vars(module).items():
            if isinstance(value, types.ModuleType):
                if value.__name__.split(".")[0] not in ALLOWED_MODULES:
                    names.add(attr)
                queue.append(value)
    return frozenset(names)


def _forbidden_attr(attr: str) -> bool:
    return (
        attr.startswith(FORBIDDEN_ATTR_PREFIXES)
        or attr in FORBIDDEN_ATTRS
        or attr in _module_attrs()
    )


def _check_module(name: str) -> None:
    if name.split(".")[0] not in ALLOWED_MODULES:
        allowed = ", ".join(sorted(ALLOWED_MODULES))
        raise UnsafeCodeError(f"Модуль '{name}' запрещён. Разрешены: {allowed}")


def run_sandboxed(code: str, params: Dict[str, Any], timeout: float = TIMEOUT_SECONDS) -> Any:
    """Выполняет run(**params) из кода в отдельном процессе и возвращает результат."""
    check_code(code)
    payload = json.dumps({
        "code": code,
        "params": params,
        "allowed": sorted(ALLOWED_MODULES),
        "forbidden": sorted(FORBIDDEN_NAMES),
    })
    with tempfile.TemporaryDirectory() as workdir:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", RUNNER],
                input=payload,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=workdir,
                env={},
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Инструмент работал дольше {timeout} с и был остановлен") from None
    if proc.returncode != 0:
        error = proc.stderr.strip().splitlines()[-1:] or ["неизвестная ошибка"]
        raise RuntimeError(f"Ошибка в инструменте: {error[0][:500]}")
    try:
        return json.loads(proc.stdout[:MAX_OUTPUT_CHARS])["result"]
    except (json.JSONDecodeError, KeyError):
        raise RuntimeError("Инструмент вернул некорректный результат") from None


def build_tool(record: CustomToolRecord, runner: Callable[..., Any] = run_sandboxed) -> Tool:
    """Превращает одобренную запись в инструмент агента."""

    def handler(**params: Any) -> Any:
        return runner(record.code, params)

    return Tool(
        name=record.name,
        description=f"[Создан агентом] {record.description}",
        input_schema=record.input_schema,
        handler=handler,
    )


def validate_proposal(name: str, parameters: Dict[str, Any], code: str) -> Dict[str, Any]:
    """Проверяет предложение инструмента; возвращает строгую схему параметров."""
    if not NAME_PATTERN.match(name):
        raise ValueError("Имя: латиница в нижнем регистре, цифры и _, от 3 до 41 символа")
    if not isinstance(parameters, dict) or not parameters:
        raise ValueError("parameters: объект {имя: {type, description}} хотя бы с одним полем")
    allowed_types = {"string", "number", "integer", "boolean"}
    for key, spec in parameters.items():
        if not re.match(r"^[a-z][a-z0-9_]{0,40}$", key):
            raise ValueError(f"Некорректное имя параметра '{key}'")
        if not isinstance(spec, dict) or spec.get("type") not in allowed_types:
            raise ValueError(f"Параметр '{key}': type должен быть одним из {sorted(allowed_types)}")
    check_code(code)
    schema = make_schema({
        key: {"type": spec["type"], "description": str(spec.get("description", ""))}
        for key, spec in parameters.items()
    })
    return schema


def propose_tool_tool(store: Store, existing_names: Callable[[], List[str]]) -> Tool:
    """Инструмент, через который агент предлагает новый инструмент."""

    def propose(name: str, description: str, parameters_json: str, code: str) -> str:
        if name in existing_names():
            raise ValueError(f"Инструмент '{name}' уже существует")
        try:
            parameters = json.loads(parameters_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"parameters_json - некорректный JSON: {e}") from None
        schema = validate_proposal(name, parameters, code)
        store.add_custom_tool(name, description, schema, code)
        return (
            f"Инструмент '{name}' сохранён и ждёт проверки пользователем. Он станет "
            "доступен после одобрения. Сообщи пользователю, что предложил инструмент "
            "и зачем он нужен."
        )

    return Tool(
        name="propose_tool",
        description=(
            "Предлагает новый инструмент, если для задач регулярно не хватает какого-то "
            "расчёта или преобразования данных. Код на Python должен определять функцию "
            "run(**params) и возвращать JSON-совместимый результат. Разрешены только "
            f"модули: {', '.join(sorted(ALLOWED_MODULES))}. Нет доступа к файлам, сети и "
            "системе. Инструмент заработает только после одобрения пользователем."
        ),
        input_schema=make_schema({
            "name": {"type": "string", "description": "snake_case, например vat_calc"},
            "description": {"type": "string", "description": "Что делает и когда вызывать"},
            "parameters_json": {
                "type": "string",
                "description": (
                    'JSON-объект параметров: {"amount": {"type": "number", '
                    '"description": "Сумма"}}. Типы: string, number, integer, boolean'
                ),
            },
            "code": {"type": "string", "description": "Код с функцией run(**params)"},
        }),
        handler=propose,
    )
