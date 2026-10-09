# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

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
        line = progress_markup(event)
        if line:
            self.console.print(line, highlight=False)


def progress_markup(event: Event) -> str:
    """Строка прогресса для события (разметка rich) или пустая строка."""
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
    if event.type == ev.INJECTION_WARNING:
        snippet = (data.get("snippets") or [""])[0]
        return (
            f"[bold red]⚠ Подозрительный текст в данных ({escape(data['tool'])}): "
            f"«{escape(short(snippet, 90))}» — агент не будет его выполнять[/]"
        )
    if event.type == ev.COMPACTION:
        return "[dim]↻ История диалога сжата: старая часть заменена кратким содержанием[/]"
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
    searches = f", поисков {usage.web_search_requests}" if usage.web_search_requests else ""
    console.print(
        f"[dim]Токены: вход {usage.input_tokens}{cached}, выход {usage.output_tokens}"
        f"{searches} · {format_usd(usage.cost_usd)}[/]",
        highlight=False,
    )


def format_usd(value: float) -> str:
    return f"${value:.4f}" if value < 0.01 else f"${value:.2f}"


def print_llm_error(console: Console, error: Exception) -> None:
    from prizolov_os.budget import BudgetExceeded

    if isinstance(error, BudgetExceeded):
        console.print(f"[yellow]{escape(str(error))}[/]")
    else:
        console.print(f"[red]Ошибка модели: {escape(str(error))}[/]")


def print_code(console: Console, code: str, title: str) -> None:
    console.print(Panel(Syntax(code, "python", line_numbers=True), title=escape(title)))


def print_report(console: Console, report: Any) -> None:
    """Отчёт по активу: состояние, таблица прогнозов, надёжность."""
    from rich.table import Table

    from prizolov_os.reports import DISCLAIMER, TABLE_HEADER, table_rows

    s = report.summary
    console.print(f"[bold]Отчёт: {escape(report.title)}[/]  "
                  f"[dim]{s['first_date']} – {s['last_date']}, {s['observations']} наблюдений[/]")
    console.print(
        f"Цена {report.last_price:,.2f} ({s['last_date']}) · за период {s['change_pct']:+.2f}% · "
        f"волатильность {s['volatility_annual_pct']}% · RSI {s['indicators'].get('rsi_14')}"
        .replace(",", " "), highlight=False,
    )
    table = Table(*TABLE_HEADER, title="Прогнозы", show_lines=False)
    for cells in table_rows(report):
        table.add_row(*[escape(c) for c in cells])
    console.print(table)
    for row in report.rows:
        summary = escape(row.reliability.get("summary", ""))
        console.print(f"[dim]{row.horizon_days} дн.: {summary}[/]")
    console.print(f"[italic]{escape(DISCLAIMER)}[/]")
