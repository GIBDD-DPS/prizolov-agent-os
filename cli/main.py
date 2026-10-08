#!/usr/bin/env python3
# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Командная строка Prizolov Agent OS.

    prizolov chat [--session ID]   интерактивный диалог
    prizolov run "задача"          одна задача
    prizolov sessions              сохранённые диалоги
"""

import argparse
import logging
import os
import sys
from typing import Callable, List, Optional

from rich.console import Console

from prizolov_os.__about__ import HEADER, PROJECT_ID
from prizolov_os.config import settings
from prizolov_os.core.kernel import SELF_CHECK_MODES, Kernel
from prizolov_os.logging_config import setup_logging

from .app import ChatApp, run_once
from .render import InputFn, ProgressPrinter, make_approver

KernelFactory = Callable[..., Kernel]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prizolov", description="Prizolov Agent OS - команда ИИ-агентов"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="подробный лог в консоли")
    parser.add_argument("--version", action="version", version=f"{HEADER}\n{PROJECT_ID}")
    parser.add_argument(
        "--self-check", choices=SELF_CHECK_MODES, help="режим самопроверки ответов"
    )
    sub = parser.add_subparsers(dest="command")
    chat = sub.add_parser("chat", help="интерактивный диалог (по умолчанию)")
    chat.add_argument("--session", help="продолжить сохранённый диалог")
    run = sub.add_parser("run", help="выполнить одну задачу")
    run.add_argument("task", nargs="+", help="текст задачи")
    sub.add_parser("sessions", help="список сохранённых диалогов")
    return parser


def main(
    argv: Optional[List[str]] = None,
    *,
    console: Optional[Console] = None,
    ask: Optional[InputFn] = None,
    kernel_factory: KernelFactory = Kernel.create,
) -> int:
    args = build_parser().parse_args(argv)
    console = console or Console()
    ask = ask or _make_input(console)

    try:
        settings.validate()
    except ValueError as e:
        console.print(f"[red]Ошибка конфигурации: {e}[/]")
        return 1
    # Ошибки инструментов и так видны в строках прогресса; в лог консоли - только сбои.
    setup_logging(level=logging.DEBUG if args.verbose else logging.ERROR)

    if args.command != "sessions" and not _has_credentials():
        console.print(
            "[yellow]Не найден ключ Anthropic. Добавьте в .env строку "
            "ANTHROPIC_API_KEY=... (ключ: https://console.anthropic.com/)[/]"
        )

    kernel = kernel_factory(
        approver=make_approver(console, ask), self_check=args.self_check
    )
    kernel.events.subscribe(ProgressPrinter(console))
    app = ChatApp(kernel, console, ask)

    if args.command == "sessions":
        app.cmd_sessions("")
        return 0
    if args.command == "run":
        return run_once(kernel, console, " ".join(args.task))

    _verify_on_start(app)
    _index_on_start(app)
    if getattr(args, "session", None):
        try:
            app.cmd_resume(args.session)
        except ValueError as e:
            console.print(f"[red]{e}[/]")
            return 1
    app.loop()
    return 0


def _verify_on_start(app: ChatApp) -> None:
    """Сверяет наступившие прогнозы при запуске чата, чтобы система училась на фактах."""
    try:
        report = app.kernel.verify_forecasts()
    except Exception as e:  # noqa: BLE001 - сверка не должна мешать запуску
        logging.getLogger(__name__).error("Forecast verification failed: %s", e)
        return
    if report.verified:
        app.print_verification(report)


def _index_on_start(app: ChatApp) -> None:
    """Обновляет базу знаний по документам рабочей папки."""
    if app.kernel.knowledge is None:
        return
    try:
        app.print_index(app.kernel.knowledge.index())
    except Exception as e:  # noqa: BLE001 - индексация не должна мешать запуску
        logging.getLogger(__name__).error("Knowledge indexing failed: %s", e)


def _has_credentials() -> bool:
    return bool(settings.api_key or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def _make_input(console: Console) -> InputFn:
    try:
        import readline  # noqa: F401 - история и редактирование строки ввода
    except ImportError:
        pass
    return lambda prompt: console.input(prompt)


if __name__ == "__main__":
    sys.exit(main())
