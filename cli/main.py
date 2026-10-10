#!/usr/bin/env python3
# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Командная строка Prizolov Agent OS.

    prizolov init                  пошаговая настройка
    prizolov doctor                проверка установки
    prizolov chat [--session ID]   интерактивный диалог
    prizolov run "задача"          одна задача
    prizolov sessions              сохранённые диалоги
    prizolov report GOLD           отчёт по активу без Claude
    prizolov cashflow bank.csv     анализ выписки без Claude (1С, CSV, Excel)
    prizolov calendar              платёжный календарь
    prizolov accuracy              страница точности прогнозов
    prizolov portfolio мой.csv     портфель: риск, стресс-тесты, прогнозы
    prizolov tenders мебель        поиск госзакупок
    prizolov mcp                   MCP-сервер для Claude Desktop и Cursor
    prizolov telegram              Telegram-бот
    prizolov api                   HTTP API
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable, List, Optional

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
    sub.add_parser("init", help="пошаговая настройка: ключ Claude, модель, Telegram, API")
    doctor = sub.add_parser("doctor", help="проверить установку: ключ, источники котировок, папки")
    doctor.add_argument("--offline", action="store_true", help="без проверок по сети")
    chat = sub.add_parser("chat", help="интерактивный диалог (по умолчанию)")
    chat.add_argument("--session", help="продолжить сохранённый диалог")
    run = sub.add_parser("run", help="выполнить одну задачу")
    run.add_argument("task", nargs="+", help="текст задачи")
    sub.add_parser("sessions", help="список сохранённых диалогов")
    report = sub.add_parser("report", help="отчёт по активу без Claude: прогнозы, таблица, график")
    report.add_argument(
        "symbol", nargs="?", help="тикер или код: GOLD, USD (ЦБ), GC=F, BTC-USD (Yahoo), SBER"
    )
    report.add_argument("--file", help="свои цены: CSV или Excel с колонками даты и цены")
    report.add_argument("--source", choices=["yahoo", "moex", "cbr"], help="источник данных")
    report.add_argument("--horizons", default="1,7,15,30", help="горизонты в днях через запятую")
    report.add_argument("--history", type=int, default=365, help="дней истории")
    cashflow = sub.add_parser(
        "cashflow", help="анализ выписки без Claude: остаток, кассовый разрыв, график"
    )
    cashflow.add_argument(
        "file", help="выписка: выгрузка клиент-банка для 1С (.txt), CSV или Excel"
    )
    cashflow.add_argument(
        "--balance", type=float, default=None,
        help="остаток на начало выписки (для 1С берётся из файла)",
    )
    cashflow.add_argument("--days", type=int, default=30, help="горизонт прогноза, дней")
    calendar = sub.add_parser("calendar", help="платёжный календарь: плановые платежи")
    calendar_sub = calendar.add_subparsers(dest="action")
    calendar_sub.add_parser("list", help="список плановых платежей")
    add = calendar_sub.add_parser("add", help="добавить платёж (минус) или поступление (плюс)")
    add.add_argument("title", help="что за платёж: «Аренда офиса»")
    add.add_argument("amount", type=float, help="сумма: платёж -180000, поступление 250000")
    add.add_argument("date", help="дата первого платежа: 2026-11-01 или 01.11.2026")
    add.add_argument("--repeat", default="разово",
                     help="разово, еженедельно, ежемесячно, ежеквартально")
    add.add_argument("--until", help="дата окончания повторов")
    remove = calendar_sub.add_parser("remove", help="удалить плановый платёж")
    remove.add_argument("id", type=int)
    portfolio = sub.add_parser(
        "portfolio", help="портфель инвестора: риск, стресс-тесты, прогнозы (без Claude)"
    )
    portfolio.add_argument("file", nargs="?", help="CSV или Excel: тикер, количество[, источник]")
    portfolio.add_argument("--tinvest", action="store_true",
                           help="взять позиции из брокерского счёта T-Invest (нужен токен)")
    portfolio.add_argument("--days", type=int, default=30, help="горизонт прогноза, дней")
    tenders = sub.add_parser("tenders", help="поиск госзакупок 44-ФЗ / 223-ФЗ (без Claude)")
    tenders.add_argument("query", nargs="+", help="что ищем: «поставка офисной мебели»")
    tenders.add_argument("--max-price", type=float, default=0, help="максимальная цена, руб.")
    tenders.add_argument("--new", action="store_true", help="только ещё не показанные")
    sub.add_parser("mcp", help="MCP-сервер для Claude Desktop, Cursor и других (stdio)")
    accuracy = sub.add_parser("accuracy", help="страница точности прогнозов (HTML)")
    accuracy.add_argument("--out", help="куда сохранить (по умолчанию workspace/reports)")
    evals = sub.add_parser(
        "eval", help="проверить агентов на настоящей модели (тратит токены)"
    )
    evals.add_argument("ids", nargs="*", help="какие проверки запустить (по умолчанию все)")
    evals.add_argument("--list", action="store_true", help="показать список проверок")
    evals.add_argument("--no-judge", action="store_true",
                       help="без модели-оценщика: только проверки по правилам")
    evals.add_argument("--max-usd", type=float, default=10.0,
                       help="остановиться, когда потрачено столько долларов")
    evals.add_argument("--out", help="папка для отчёта (по умолчанию workspace/reports)")
    sub.add_parser("telegram", help="запустить Telegram-бота (с расписанием)")
    sub.add_parser("scheduler", help="запустить только планировщик задач")
    api = sub.add_parser("api", help="запустить HTTP API (документация: /docs)")
    api.add_argument("--host", help="адрес (по умолчанию PRIZOLOV_API_HOST или 127.0.0.1)")
    api.add_argument("--port", type=int, help="порт (по умолчанию PRIZOLOV_API_PORT или 8800)")
    api.add_argument(
        "--scheduler", action="store_true",
        help="выполнять задачи по расписанию в этом же процессе (если не запущен бот)",
    )
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

    if args.command == "init":
        from getpass import getpass

        from .onboarding import run_init

        return run_init(console, ask, getpass)
    if args.command == "doctor":
        from .onboarding import run_doctor

        setup_logging(level=logging.DEBUG if args.verbose else logging.CRITICAL)
        return run_doctor(console, settings, online=not args.offline)
    try:
        settings.validate()
    except ValueError as e:
        console.print(f"[red]Ошибка конфигурации: {e}[/]")
        return 1
    if args.command == "report":
        setup_logging(level=logging.DEBUG if args.verbose else logging.ERROR)
        return run_report(console, args)
    if args.command == "cashflow":
        setup_logging(level=logging.DEBUG if args.verbose else logging.ERROR)
        return run_cashflow(console, args)
    if args.command == "portfolio":
        setup_logging(level=logging.DEBUG if args.verbose else logging.ERROR)
        return run_portfolio(console, args)
    if args.command == "mcp":
        from .mcp_server import run as run_mcp

        return run_mcp()
    if args.command == "tenders":
        setup_logging(level=logging.DEBUG if args.verbose else logging.ERROR)
        return run_tenders(console, args)
    if args.command == "accuracy":
        setup_logging(level=logging.DEBUG if args.verbose else logging.ERROR)
        return run_accuracy(console, args)
    if args.command == "eval":
        setup_logging(level=logging.DEBUG if args.verbose else logging.ERROR)
        return run_eval(console, args, kernel_factory)
    if args.command == "calendar":
        setup_logging(level=logging.DEBUG if args.verbose else logging.ERROR)
        return run_calendar(console, args)
    if args.command == "scheduler":
        setup_logging(level=logging.DEBUG if args.verbose else logging.INFO)
        return run_scheduler(console, kernel_factory)
    if args.command == "api":
        from .api.server import run as run_api

        setup_logging(level=logging.DEBUG if args.verbose else logging.WARNING)
        return run_api(args.host, args.port, args.scheduler)
    if args.command == "telegram":
        from .telegram.bot import run as run_telegram

        setup_logging(level=logging.DEBUG if args.verbose else logging.WARNING)
        return run_telegram()
    # Ошибки инструментов и так видны в строках прогресса; в лог консоли - только сбои.
    setup_logging(level=logging.DEBUG if args.verbose else logging.ERROR)

    if args.command != "sessions" and not _has_credentials():
        console.print(
            "[yellow]Не найден ключ Anthropic. Запустите prizolov init или добавьте в .env "
            "строку ANTHROPIC_API_KEY=... (ключ: https://console.anthropic.com/)[/]"
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


def run_report(console: Console, args: argparse.Namespace, market: Any = None) -> int:
    """prizolov report: прогнозы без участия модели, сохраняются в журнал для сверки."""
    from prizolov_os.forecasting import ForecastEngine, ForecastJournal
    from prizolov_os.market import MarketData, MarketDataError
    from prizolov_os.memory import Store
    from prizolov_os.reports import load_price_file, market_report, save_report

    from .render import print_report

    if not args.symbol and not args.file:
        console.print("[red]Укажите тикер (prizolov report GOLD) или файл (--file prices.csv)[/]")
        return 1
    try:
        horizons = sorted({int(h) for h in args.horizons.split(",") if h.strip()})
    except ValueError:
        console.print("[red]--horizons: числа через запятую, например 1,7,15,30[/]")
        return 1
    if not horizons or not all(1 <= h <= 365 for h in horizons):
        console.print("[red]Горизонты должны быть от 1 до 365 дней[/]")
        return 1
    engine = ForecastEngine(ForecastJournal(Store(settings.db_path)))
    try:
        series = load_price_file(Path(args.file)) if args.file else None
        report = market_report(
            market or MarketData(), engine, args.symbol or "", args.source, horizons,
            args.history, series=series,
        )
    except MarketDataError as e:
        console.print(f"[red]Не удалось получить котировки: {e}[/]")
        return 1
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/]")
        return 1
    path = save_report(report, Path(settings.workspace_dir) / "reports")
    print_report(console, report)
    console.print(f"\nОтчёт: {path}\nГрафик: {report.chart}")
    console.print("[dim]Прогнозы записаны в журнал и будут сверены с фактом (/forecasts).[/]")
    return 0


def run_cashflow(console: Console, args: argparse.Namespace) -> int:
    """prizolov cashflow: анализ выписки и прогноз остатка без участия модели."""
    from prizolov_os import charts
    from prizolov_os.analytics import analyze_cashflow
    from prizolov_os.analytics.categories import by_category
    from prizolov_os.analytics.statements import load_statement
    from prizolov_os.memory import Store
    from prizolov_os.payment_calendar import PaymentCalendar, project

    from .render import print_cashflow, print_payment_calendar

    if not 1 <= args.days <= 365:
        console.print("[red]--days: от 1 до 365[/]")
        return 1
    path = Path(args.file)
    try:
        statement = load_statement(path)
        transactions = statement.transactions
        if args.balance is not None:
            opening = args.balance
        else:
            opening = statement.opening_balance or 0.0
        analysis = analyze_cashflow(transactions, opening, args.days)
        planned = PaymentCalendar(Store(settings.db_path)).list()
        plan = project(transactions, opening, planned, args.days) if planned else None
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/]")
        return 1
    out = Path(settings.workspace_dir) / "reports"
    out.mkdir(parents=True, exist_ok=True)
    stem = "".join(c if c.isalnum() else "_" for c in path.stem)
    balance = charts.cashflow_forecast_chart(
        out / f"cashflow-{stem}.png", transactions, opening, analysis["forecast"]
    )
    monthly = charts.monthly_flows_chart(out / f"cashflow-{stem}-months.png", analysis["monthly"])
    if statement.source_format == "1c":
        source = "выписка 1С" + (", остаток на начало из файла" if args.balance is None
                                 and statement.opening_balance is not None else "")
        console.print(f"[dim]{source}[/]")
    print_cashflow(console, analysis, by_category(transactions))
    if plan is not None:
        print_payment_calendar(console, plan)
    else:
        console.print("[dim]Добавьте плановые платежи (prizolov calendar add), и прогноз "
                      "покажет день кассового разрыва.[/]")
    console.print(f"\nГрафики: {balance}\n         {monthly}")
    return 0


def run_portfolio(console: Console, args: argparse.Namespace, market: Any = None) -> int:
    """prizolov portfolio: анализ портфеля без участия модели."""
    from prizolov_os.forecasting import ForecastEngine
    from prizolov_os.market import MarketData
    from prizolov_os.portfolio import (
        PortfolioError,
        TInvestClient,
        analyze_portfolio,
        load_portfolio,
    )

    from .render import print_portfolio

    if not args.file and not args.tinvest:
        console.print("[red]Укажите файл (prizolov portfolio мой.csv) или --tinvest[/]")
        return 1
    if not 1 <= args.days <= 365:
        console.print("[red]--days: от 1 до 365[/]")
        return 1
    try:
        if args.tinvest:
            positions = TInvestClient(settings.tinvest_token or "").positions()
        else:
            positions = load_portfolio(Path(args.file))
        result = analyze_portfolio(positions, market or MarketData(), ForecastEngine(),
                                   args.days)
    except (OSError, PortfolioError, ValueError) as e:
        console.print(f"[red]{e}[/]")
        return 1
    print_portfolio(console, result)
    return 0


def run_tenders(console: Console, args: argparse.Namespace, fetch: Any = None) -> int:
    """prizolov tenders: открытые закупки в ЕИС по запросу."""
    from rich.markup import escape
    from rich.table import Table

    from prizolov_os.memory import Store
    from prizolov_os.tenders import TenderSearch, TenderSearchError

    try:
        tenders = TenderSearch(Store(settings.db_path), fetch).search(
            " ".join(args.query), max_price=args.max_price, only_new=args.new,
        )
    except (TenderSearchError, ValueError) as e:
        console.print(f"[red]{e}[/]")
        return 1
    if not tenders:
        console.print("Закупок не найдено." + (" Новых нет." if args.new else ""))
        return 0
    table = Table("Номер", "Предмет", "Заказчик", "Цена, ₽", "Подача до", "",
                  title=f"Закупки: {escape(' '.join(args.query))}")
    for t in tenders:
        price = f"{t.price:,.0f}".replace(",", " ") if t.price else "—"
        table.add_row(t.number, escape(t.title[:90]), escape(t.customer[:50]), price,
                      t.deadline or "—", "[green]новая[/]" if t.new else "")
    console.print(table)
    for t in tenders:
        console.print(f"[dim]{t.number}: {t.url}[/]", highlight=False)
    return 0


def run_accuracy(console: Console, args: argparse.Namespace) -> int:
    """prizolov accuracy: открытая статистика точности прогнозов в HTML."""
    from prizolov_os.accuracy import accuracy_data, render_html
    from prizolov_os.memory import Store

    data = accuracy_data(Store(settings.db_path))
    out = Path(args.out) if args.out else Path(settings.workspace_dir) / "reports" / "accuracy.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(data), encoding="utf-8")
    o = data["overall"]
    if o["forecasts"]:
        console.print(f"Сверено прогнозов: {o['forecasts']}; в интервале 80%: "
                      f"{o['interval_80_pct']}%; направление угадано: {o['direction_pct']}%")
    else:
        console.print(f"Сверенных прогнозов пока нет; ожидают срока: {data['pending']}.")
    console.print(f"Страница: {out}")
    return 0


def run_eval(
    console: Console,
    args: argparse.Namespace,
    kernel_factory: KernelFactory = Kernel.create,
    judge_factory: Optional[Callable[[], Any]] = None,
) -> int:
    """prizolov eval: проверка агентов на эталонных задачах с настоящей моделью."""
    from datetime import datetime

    from prizolov_os import evals
    from prizolov_os.evals.cases import CASES
    from prizolov_os.llm import create_client

    if args.list:
        for case in CASES:
            console.print(f"{case.id:<22} {case.title}")
        return 0
    try:
        cases = evals.select(CASES, args.ids)
    except evals.EvalError as e:
        console.print(f"[red]{e}[/]")
        return 1
    if judge_factory is None and not _has_credentials():
        console.print(
            "[red]Нужен ключ Anthropic: проверки идут на настоящей модели. Добавьте в .env "
            "строку ANTHROPIC_API_KEY=... или запустите prizolov init.[/]"
        )
        return 1
    judge_llm = None if args.no_judge else (judge_factory or create_client)()
    console.print(
        f"Проверок: {len(cases)}, модель {settings.model}, лимит ${args.max_usd:.2f}. "
        "Это займёт несколько минут."
    )

    def show(result: Any) -> None:
        mark = "[green]✓[/]" if result.passed else "[red]✗[/]"
        failed = [c.name for c in result.checks if not c.ok] or ([result.error] if result.error
                                                              else [])
        tail = f" — {'; '.join(failed)}" if failed else ""
        console.print(f"{mark} {result.case_id} (${result.cost_usd:.3f}){tail}", markup=True,
                      highlight=False)

    try:
        results = evals.run_all(cases, kernel_factory=kernel_factory, judge_llm=judge_llm,
                                max_usd=args.max_usd, on_result=show)
    except evals.EvalError as e:
        console.print(f"[red]{e}[/]")
        return 1
    out_dir = Path(args.out) if args.out else Path(settings.workspace_dir) / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"evals-{datetime.now():%Y%m%d-%H%M}"
    stem.with_suffix(".md").write_text(evals.to_markdown(results, settings.model),
                                       encoding="utf-8")
    stem.with_suffix(".json").write_text(evals.to_json(results, settings.model),
                                         encoding="utf-8")
    s = evals.summary(results)
    console.print(
        f"Пройдено {s['passed']} из {s['total']} ({s['pass_rate_pct']}%), "
        f"потрачено ${s['cost_usd']:.2f}. Отчёт: {stem.with_suffix('.md')}"
    )
    return 0 if s["passed"] == s["total"] else 1


def run_calendar(console: Console, args: argparse.Namespace) -> int:
    """prizolov calendar: плановые платежи для платёжного календаря."""
    from prizolov_os.analytics.cashflow import parse_date
    from prizolov_os.memory import Store
    from prizolov_os.payment_calendar import PaymentCalendar, parse_repeat

    from .render import print_planned

    calendar = PaymentCalendar(Store(settings.db_path))
    try:
        if args.action == "add":
            payment = calendar.add(
                args.title, args.amount, parse_date(args.date), parse_repeat(args.repeat),
                parse_date(args.until) if args.until else None,
            )
            console.print(f"Добавлено #{payment.id}: {payment.title}, {payment.amount:,.2f}"
                          .replace(",", " ") + f", {payment.as_dict()['repeat_name']} с "
                          f"{payment.due_date:%d.%m.%Y} ({payment.category})")
        elif args.action == "remove":
            if not calendar.remove(args.id):
                console.print(f"[red]Нет планового платежа #{args.id}[/]")
                return 1
            console.print(f"Удалено #{args.id}")
        else:
            print_planned(console, calendar.list())
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        return 1
    return 0


def run_scheduler(console: Console, kernel_factory: KernelFactory) -> int:
    """prizolov scheduler: выполняет задачи по расписанию; результаты - в workspace/reports.

    Результаты для Telegram-чатов доставляются, только если запущен бот
    (prizolov telegram запускает планировщик сам).
    """
    import threading

    from prizolov_os.scheduler import ScheduleRunner

    kernel = kernel_factory()
    kernel.schedules.ensure_builtin()
    tasks = kernel.schedules.list()
    console.print(f"Планировщик запущен: задач {len(tasks)}. Ctrl+C - остановить.")
    stop = threading.Event()
    try:
        ScheduleRunner(kernel).run_forever(stop)
    except KeyboardInterrupt:
        stop.set()
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
