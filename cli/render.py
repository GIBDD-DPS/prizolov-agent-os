"""Вывод в терминал: прогресс агентов, подтверждения, ответы."""

import json
from typing import Any, Callable, Dict

from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax

from prizolov_os import events as ev
from prizolov_os.events import Event
from prizolov_os.llm import Usage

AGENT_NAMES = {
    "director": "Директор",
    "assistant": "Ассистент",
    "researcher": "Исследователь",
    "writer": "Писатель",
    "cashflow_analyst": "Финансовый аналитик",
    "market_analyst": "Рыночный аналитик",
    "critic": "Критик",
}
PREVIEW_LINES = 15

InputFn = Callable[[str], str]


def agent_title(name: str) -> str:
    return AGENT_NAMES.get(name, name)


def short(value: Any, limit: int = 80) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_params(params: Dict[str, Any]) -> str:
    return ", ".join(f"{key}={short(value, 40)}" for key, value in params.items())


class ProgressPrinter:
    """Печатает события агентов одной строкой каждое."""

    def __init__(self, console: Console) -> None:
        self.console = console

    def __call__(self, event: Event) -> None:
        line = self._line(event)
        if line:
            self.console.print(line, highlight=False)

    def _line(self, event: Event) -> str:
        data, who = event.data, escape(agent_title(event.agent))
        if event.type == ev.DELEGATION_START:
            specialist = escape(agent_title(data["specialist"]))
            return f"[cyan]→ {who} → {specialist}:[/] [dim]{escape(short(data['task'], 60))}[/]"
        if event.type == ev.DELEGATION_END:
            specialist = escape(agent_title(data["specialist"]))
            if data["status"] == "end_turn":
                return f"[green]✓ {specialist} закончил[/]"
            return f"[yellow]! {specialist}: {escape(str(data['status']))}[/]"
        if event.type == ev.TOOL_CALL and data["tool"] != "delegate":
            tool = escape(data["tool"])
            params = escape(format_params(data.get("input") or {}))
            where = " (сервер)" if data.get("server") else ""
            return f"[dim]  ⚙ {who}: {tool}({params}){where}[/]"
        if event.type == ev.TOOL_RESULT and data.get("is_error"):
            return f"[yellow]  ! {escape(data['tool'])}: {escape(short(data['output'], 120))}[/]"
        if event.type == ev.SELF_CHECK:
            color = "green" if data["score"] >= 7 else "yellow"
            return f"[{color}]✓ Самопроверка: {data['score']}/10[/]"
        if event.type == ev.REVISION:
            issues = "; ".join(data.get("issues") or [])
            return f"[yellow]↻ Дорабатываю ответ: {escape(short(issues, 120))}[/]"
        return ""


def make_approver(console: Console, ask: InputFn) -> Callable[[str, Dict[str, Any]], bool]:
    """Спрашивает человека перед опасным действием (запись файла и т. п.)."""

    def approve(tool: str, params: Dict[str, Any]) -> bool:
        if tool == "write_file":
            content = str(params.get("content", ""))
            lines = content.splitlines()
            preview = "\n".join(lines[:PREVIEW_LINES])
            if len(lines) > PREVIEW_LINES:
                preview += f"\n… ещё {len(lines) - PREVIEW_LINES} строк"
            console.print(Panel(
                escape(preview) or "(пустой файл)",
                title=f"Запись в файл: {escape(str(params.get('path', '')))}",
                border_style="yellow",
            ))
        else:
            console.print(f"[yellow]Агент хочет выполнить {escape(tool)}"
                          f"({escape(format_params(params))})[/]")
        return confirm(ask, "Разрешить?")

    return approve


def confirm(ask: InputFn, question: str) -> bool:
    try:
        answer = ask(f"{question} [y/N] ")
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in {"y", "yes", "д", "да"}


def print_answer(console: Console, text: str) -> None:
    console.print()
    console.print(Markdown(text or "_(пустой ответ)_"))
    console.print()


def print_usage(console: Console, usage: Usage) -> None:
    cached = f" (из кэша {usage.cache_read_input_tokens})" if usage.cache_read_input_tokens else ""
    console.print(
        f"[dim]Токены: вход {usage.input_tokens}{cached}, выход {usage.output_tokens}[/]",
        highlight=False,
    )


def print_code(console: Console, code: str, title: str) -> None:
    console.print(Panel(Syntax(code, "python", line_numbers=True), title=escape(title)))
