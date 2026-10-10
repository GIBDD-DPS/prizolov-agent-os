# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""MCP-сервер Prizolov: инструменты для Claude Desktop, Cursor и других MCP-клиентов.

    prizolov mcp      (pip install "prizolov-os[mcp]")

Инструменты работают без ключа Claude: модель - у клиента. Файлы - из рабочей
папки PRIZOLOV_WORKSPACE и папок из PRIZOLOV_MCP_ROOTS (через запятую).
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from prizolov_os.__about__ import HEADER, __title__, __url__, __version__

INSTRUCTIONS = (
    f"{HEADER}. Инструменты для бизнеса и инвестора на российских данных: прогнозы цен "
    "металлов, валют, акций Мосбиржи и криптовалют (ЦБ РФ, Мосбиржа, Yahoo) с честной "
    "статистикой точности; анализ банковских выписок (формат 1С, CSV, Excel) и платёжный "
    "календарь с днём кассового разрыва; портфель инвестора (риск, стресс-тесты); поиск "
    "госзакупок 44-ФЗ/223-ФЗ; сравнение версий договоров; поиск по документам пользователя. "
    "Прогнозы - статистическая оценка, а не инвестиционная рекомендация."
)


class Paths:
    """Пути к файлам: относительные - от рабочей папки; абсолютные - только внутри
    рабочей папки или разрешённых папок."""

    def __init__(self, workspace: Path, roots: Sequence[Path] = ()) -> None:
        self.workspace = Path(workspace).resolve()
        self.roots = [self.workspace, *(Path(r).expanduser().resolve() for r in roots)]

    def resolve(self, path: str) -> Path:
        raw = Path(path).expanduser()
        target = (raw if raw.is_absolute() else self.workspace / raw).resolve()
        if not any(target == root or target.is_relative_to(root) for root in self.roots):
            allowed = ", ".join(str(r) for r in self.roots)
            raise PermissionError(
                f"Файл вне разрешённых папок ({allowed}). Добавьте папку в PRIZOLOV_MCP_ROOTS."
            )
        if not target.is_file():
            raise FileNotFoundError(f"Файл не найден: {path}")
        return target


def _tool_error() -> Any:
    try:
        from mcp.server.mcpserver.exceptions import ToolError  # mcp 2.x
    except ImportError:
        from mcp.server.fastmcp.exceptions import (  # type: ignore[no-redef]  # mcp 1.x
            ToolError,
        )
    return ToolError


def _friendly(fn: Any) -> Any:
    """Ожидаемые ошибки (нет связи с источником, неверный файл) - понятным текстом
    для клиента, без трассировки."""
    import functools

    from prizolov_os.market import MarketDataError
    from prizolov_os.portfolio import PortfolioError
    from prizolov_os.tenders import TenderSearchError

    expected = (ValueError, OSError, MarketDataError, PortfolioError, TenderSearchError)
    tool_error = _tool_error()

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except expected as e:
            raise tool_error(str(e)) from None

    return wrapper


def _server_class() -> Any:
    try:
        from mcp.server.mcpserver import MCPServer  # mcp 2.x

        return MCPServer
    except ImportError:
        from mcp.server.fastmcp import FastMCP  # type: ignore[attr-defined]  # mcp 1.x

        return FastMCP


def build_server(
    workspace: Path,
    store: Any,
    market: Any = None,
    roots: Sequence[Path] = (),
    tenders_fetch: Any = None,
) -> Any:
    from prizolov_os.accuracy import accuracy_data
    from prizolov_os.analytics import analyze_cashflow
    from prizolov_os.analytics.cashflow import parse_date
    from prizolov_os.analytics.categories import by_category
    from prizolov_os.analytics.statements import load_statement
    from prizolov_os.documents import extract_text, is_document
    from prizolov_os.forecasting import ForecastEngine, ForecastJournal
    from prizolov_os.knowledge import KnowledgeBase
    from prizolov_os.market import MarketData
    from prizolov_os.payment_calendar import PaymentCalendar, parse_repeat, project
    from prizolov_os.portfolio import analyze_portfolio, load_portfolio
    from prizolov_os.reports import market_report, to_markdown
    from prizolov_os.tenders import TenderSearch
    from prizolov_os.tools.contracts import compare_texts

    market = market or MarketData()
    engine = ForecastEngine(ForecastJournal(store))
    calendar = PaymentCalendar(store)
    knowledge = KnowledgeBase(store, Path(workspace))
    paths = Paths(Path(workspace), roots)
    tenders = TenderSearch(store, tenders_fetch)

    def read(path: str) -> str:
        file = paths.resolve(path)
        if is_document(file):
            return extract_text(file)
        from prizolov_os.analytics.statements import decode_text

        return decode_text(file.read_bytes())

    server_class = _server_class()
    try:
        server = server_class(name="prizolov", title=__title__, version=__version__,
                              instructions=INSTRUCTIONS, website_url=__url__)
    except TypeError:  # mcp 1.x: меньше параметров
        server = server_class(name="prizolov", instructions=INSTRUCTIONS)

    def tool() -> Any:
        def register(fn: Any) -> Any:
            server.tool()(_friendly(fn))
            return fn
        return register

    @tool()
    def market_forecast(
        symbol: str, source: str = "", horizons: str = "1,7,15,30"
    ) -> Dict[str, Any]:
        """Прогноз цены актива на несколько горизонтов (дней) с интервалами 80% и 95%,
        вероятностью роста и надёжностью метода (на скольких прогнозах проверен, процент
        попаданий). symbol: GOLD, SILVER, USD, EUR, CNY (ЦБ РФ), SBER, GAZP (Мосбиржа),
        GC=F, BTC-USD, AAPL (Yahoo). source: cbr, moex, yahoo или пусто - по тикеру."""
        days = sorted({int(h) for h in horizons.split(",") if h.strip()})
        if not days or not all(1 <= d <= 365 for d in days):
            raise ValueError("horizons: числа от 1 до 365 через запятую")
        report = market_report(market, engine, symbol, source or None, days)
        return {
            "symbol": report.symbol, "source": report.source, "currency": report.currency,
            "unit": report.unit, "last_price": report.last_price,
            "summary": report.summary,
            "forecasts": [{"horizon_days": r.horizon_days, **r.forecast} for r in report.rows],
            "report_markdown": to_markdown(report),
        }

    @tool()
    def analyze_bank_statement(path: str, opening_balance: Optional[float] = None,
                               days: int = 60) -> Dict[str, Any]:
        """Анализ банковской выписки: выгрузка клиент-банка для 1С (.txt), CSV или Excel.
        Итоги, статьи расходов, помесячные потоки, прогноз остатка и вероятность уйти в
        минус; если в платёжном календаре есть плановые платежи - день кассового разрыва и
        сумма нехватки. opening_balance: остаток на начало (для 1С берётся из файла)."""
        statement = load_statement(paths.resolve(path))
        opening = opening_balance if opening_balance is not None else (
            statement.opening_balance or 0.0
        )
        analysis = analyze_cashflow(statement.transactions, opening, days)
        planned = calendar.list()
        plan = project(statement.transactions, opening, planned, days) if planned else None
        if plan:
            plan["days"] = [d for d in plan["days"]
                            if d["planned"] or d["probability_negative"] >= 0.2]
        return {"source_format": statement.source_format, "opening_balance": opening,
                "analysis": analysis, "categories": by_category(statement.transactions),
                "payment_calendar": plan}

    @tool()
    def payment_calendar_list() -> Dict[str, Any]:
        """Плановые платежи (минус) и ожидаемые поступления (плюс) платёжного календаря."""
        return {"payments": [p.as_dict() for p in calendar.list()]}

    @tool()
    def payment_calendar_add(title: str, amount: float, due_date: str,
                             repeat: str = "разово") -> Dict[str, Any]:
        """Добавляет плановый платёж (amount < 0) или поступление (amount > 0).
        due_date: ГГГГ-ММ-ДД или ДД.ММ.ГГГГ; repeat: разово, еженедельно, ежемесячно,
        ежеквартально."""
        return calendar.add(title, amount, parse_date(due_date), parse_repeat(repeat)).as_dict()

    @tool()
    def payment_calendar_remove(payment_id: int) -> str:
        """Удаляет плановый платёж по номеру."""
        if not calendar.remove(payment_id):
            raise ValueError(f"Нет планового платежа #{payment_id}")
        return f"Удалено #{payment_id}"

    @tool()
    def portfolio_analysis(path: str, horizon_days: int = 30) -> Dict[str, Any]:
        """Портфель инвестора из CSV/Excel (тикер, количество[, источник, цена покупки]):
        стоимость в рублях, доли, волатильность, VaR 95%, просадка, стресс-тесты,
        концентрация и прогноз по каждой бумаге."""
        return analyze_portfolio(load_portfolio(paths.resolve(path)), market, engine,
                                 horizon_days)

    @tool()
    def search_tenders(query: str, max_price: float = 0, only_new: bool = False) -> Dict[
            str, Any]:
        """Открытые госзакупки 44-ФЗ и 223-ФЗ в ЕИС (zakupki.gov.ru) по запросу: номер,
        предмет, заказчик, начальная цена, срок подачи, ссылка. only_new - только ещё не
        показанные."""
        found = tenders.search(query, max_price=max_price, only_new=only_new)
        return {"found": len(found), "tenders": [t.as_dict() for t in found]}

    @tool()
    def compare_documents(old_path: str, new_path: str) -> Dict[str, Any]:
        """Сравнивает две версии договора или другого документа (PDF, Word, TXT, MD):
        добавленные, удалённые и изменённые абзацы, правки внутри абзаца [-было-] {+стало+}."""
        return compare_texts(read(old_path), read(new_path))

    @tool()
    def read_document(path: str) -> str:
        """Текст документа: PDF, Word, Excel (первый лист как CSV), TXT, MD, CSV."""
        text = read(path)
        return text if len(text) <= 200_000 else text[:200_000] + "\n[текст обрезан]"

    @tool()
    def search_documents(query: str, limit: int = 6) -> Dict[str, Any]:
        """Поиск по документам рабочей папки (локальная база знаний): фрагменты с
        указанием файла и места."""
        hits = knowledge.search(query, max(1, min(limit, 20)))
        return {"results": [{"source": h.source, "text": h.text, "score": h.score}
                            for h in hits]}

    @tool()
    def forecast_accuracy() -> Dict[str, Any]:
        """Честная статистика точности прогнозов: сколько сверено с фактом, доля фактов в
        интервале 80% (цель - около 80%), точность направления, по классам и активам."""
        return accuracy_data(store)

    return server


def configure_logging() -> None:
    """В протоколе stdio stdout занят сообщениями MCP: логи - только в stderr."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.WARNING)
    for name in ("prizolov_os", ""):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.setLevel(logging.WARNING)


def run() -> int:
    """prizolov mcp: MCP-сервер по stdio."""
    try:
        _server_class()
    except ImportError:
        print('Нужен пакет MCP: pip install "prizolov-os[mcp]"', file=sys.stderr)
        return 1
    configure_logging()
    from prizolov_os.config import settings
    from prizolov_os.memory import Store

    roots = [Path(p.strip()) for p in os.getenv("PRIZOLOV_MCP_ROOTS", "").split(",") if p.strip()]
    workspace = Path(settings.workspace_dir)
    workspace.mkdir(parents=True, exist_ok=True)
    print(f"{__title__} {__version__} MCP · {__url__}", file=sys.stderr)
    build_server(workspace, Store(settings.db_path), roots=roots).run()
    return 0


__all__ = ["INSTRUCTIONS", "Paths", "build_server", "run"]
