# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Финансовые инструменты: движение денег, котировки, анализ ценовых рядов."""

import csv
import io
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from ..analytics import analyze_cashflow, analyze_series
from ..analytics.cashflow import parse_amount, parse_date
from ..analytics.categories import by_category
from ..analytics.statements import Statement, load_statement
from ..forecasting import ForecastEngine
from ..market import CBR_CURRENCIES, CBR_METALS, SOURCES, MarketData
from .base import Tool, make_schema
from .builtin import Workspace

PRICE_COLUMNS = {"close", "цена", "price", "закрытие", "value", "курс", "adj close"}
DATE_COLUMNS = {"date", "дата", "tradedate", "дата торгов"}
MAX_HORIZON_DAYS = 365

FORECAST_NOTE = (
    "Прогноз - статистическая оценка по истории, а не предсказание и не инвестиционный "
    "совет. Метод выбран по точности на истории; надёжность - в forecast.reliability."
)


def read_statement(workspace: Workspace, path: str) -> Statement:
    """Выписка из рабочей папки: 1С, CSV или Excel."""
    return load_statement(workspace.resolve(path))


def opening_for(statement: Statement, opening_balance: float) -> float:
    """Остаток на начало: указанный пользователем, иначе - из выписки 1С, иначе 0."""
    if opening_balance:
        return opening_balance
    return statement.opening_balance or 0.0


def cashflow_tool(workspace: Workspace, engine: Optional[ForecastEngine] = None) -> Tool:
    def handler(path: str, opening_balance: float, horizon_days: int) -> Dict[str, Any]:
        _check_horizon(horizon_days)
        statement = read_statement(workspace, path)
        transactions = statement.transactions
        opening = opening_for(statement, opening_balance)
        result = analyze_cashflow(transactions, opening, horizon_days)
        result["categories"] = by_category(transactions)
        result["source_format"] = statement.source_format
        if engine:
            engine.cashflow_forecast(result, transactions, path)
        result["note"] = (
            "Прогноз остатка исходит из того, что средний дневной поток сохранится. "
            "Разовые крупные платежи сильно влияют на оценку; точнее - платёжный "
            "календарь (payment_calendar) с плановыми платежами."
        )
        if opening_balance == 0 and statement.opening_balance is not None:
            result["note"] += " Остаток на начало взят из выписки 1С."
        return result

    return Tool(
        name="analyze_cashflow",
        description=(
            "Анализирует выписку движения денег в рабочей папке и прогнозирует остаток. "
            "Форматы: выгрузка клиент-банка для 1С (.txt, 1CClientBankExchange), CSV или "
            "Excel с колонками дата, сумма (поступления +, расходы -), назначение. "
            "Возвращает итоги, помесячные потоки, статьи (categories: зарплата, налоги, "
            "аренда, поставщики...), крупнейшие расходы, ожидаемый остаток через "
            "horizon_days с интервалами 80% и 95% и вероятность уйти в минус."
        ),
        input_schema=make_schema({
            "path": {"type": "string", "description": "Путь к CSV или Excel в рабочей папке"},
            "opening_balance": {
                "type": "number",
                "description": "Остаток на начало выписки; 0 - взять из выписки 1С или 0",
            },
            "horizon_days": {"type": "integer", "description": "Горизонт прогноза в днях"},
        }),
        handler=handler,
        untrusted=True,
    )


def market_tools(
    market: MarketData, workspace: Workspace, engine: Optional[ForecastEngine] = None
) -> List[Tool]:
    engine = engine or ForecastEngine()

    def analyze_market(
        source: str, symbol: str, history_days: int, horizon_days: int
    ) -> Dict[str, Any]:
        _check_horizon(horizon_days)
        series = market.history(source, symbol, history_days)
        result = analyze_series(series.dates, series.closes, horizon_days)
        result["forecast"] = engine.market_forecast(
            series.source, series.symbol, series.dates, series.closes, horizon_days
        )
        return {
            "source": series.source,
            "symbol": series.symbol,
            "currency": series.currency,
            "unit": series.unit,
            **result,
            "note": FORECAST_NOTE,
        }

    def analyze_price_csv(path: str, horizon_days: int) -> Dict[str, Any]:
        _check_horizon(horizon_days)
        dates, closes = parse_price_csv(workspace.read_table(path))
        result = analyze_series(dates, closes, horizon_days)
        result["forecast"] = engine.market_forecast("csv", path, dates, closes, horizon_days)
        return {**result, "note": FORECAST_NOTE}

    currencies = ", ".join(CBR_CURRENCIES)
    metals = ", ".join(CBR_METALS)
    return [
        Tool(
            name="analyze_market",
            description=(
                "Загружает историю цен и возвращает анализ: изменение за период, SMA/EMA, "
                "RSI, годовую волатильность, максимальную просадку, последние цены и "
                "вероятностный прогноз (медиана, интервалы 80% и 95%, вероятность роста). "
                "Метод прогноза выбирается по точности на истории; в forecast.reliability - "
                "на скольких прогнозах он проверен, процент попаданий в интервал, точность "
                "направления и реальные сверки прошлых прогнозов. Чем длиннее история "
                "(history_days от 365), тем надёжнее проверка. "
                "Источники: "
                "yahoo - мировые рынки: акции (AAPL), индексы (^GSPC), валюты (EURUSD=X, "
                "USDRUB=X), криптовалюты (BTC-USD, ETH-USD), фьючерсы на металлы "
                "(GC=F золото, SI=F серебро, PL=F платина, PA=F палладий), нефть (BZ=F); "
                "moex - Московская биржа, акции и фонды по тикеру (SBER, GAZP, LKOH); "
                f"cbr - ЦБ РФ, официальные курсы рубля ({currencies}) и учётные цены "
                f"металлов в рублях за грамм ({metals})."
            ),
            input_schema=make_schema({
                "source": {"type": "string", "enum": list(SOURCES)},
                "symbol": {"type": "string", "description": "Тикер или код в этом источнике"},
                "history_days": {
                    "type": "integer",
                    "description": "Сколько календарных дней истории загрузить (обычно 365)",
                },
                "horizon_days": {"type": "integer", "description": "Горизонт прогноза в днях"},
            }),
            handler=analyze_market,
        ),
        Tool(
            name="analyze_price_csv",
            description=(
                "То же, что analyze_market, но для истории цен из CSV в рабочей папке. "
                "Файл CSV или Excel; колонки: дата и цена закрытия (close/цена/курс)."
            ),
            input_schema=make_schema({
                "path": {"type": "string", "description": "Путь к CSV в рабочей папке"},
                "horizon_days": {"type": "integer", "description": "Горизонт прогноза в днях"},
            }),
            handler=analyze_price_csv,
            untrusted=True,
        ),
    ]


def _check_horizon(horizon_days: int) -> None:
    if not 1 <= horizon_days <= MAX_HORIZON_DAYS:
        raise ValueError(f"Горизонт прогноза должен быть от 1 до {MAX_HORIZON_DAYS} дней")


def parse_price_csv(text: str) -> Tuple[List[date], List[float]]:
    text = text.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ValueError("В файле нет данных")
    header = [c.strip().lower() for c in rows[0]]
    date_col = next((i for i, h in enumerate(header) if h in DATE_COLUMNS), -1)
    price_col = next((i for i, h in enumerate(header) if h in PRICE_COLUMNS), -1)
    if date_col < 0 or price_col < 0:
        raise ValueError(
            f"Нужны колонки даты и цены (date/дата и close/цена). Найдены: {', '.join(header)}"
        )
    pairs: Dict[date, float] = {}
    for line_no, row in enumerate(rows[1:], start=2):
        try:
            if row[price_col].strip():
                pairs[parse_date(row[date_col])] = parse_amount(row[price_col])
        except (ValueError, IndexError) as e:
            raise ValueError(f"Строка {line_no}: {e}") from None
    ordered = sorted(pairs.items())
    return [d for d, _ in ordered], [p for _, p in ordered]


def chart_tools(
    market: MarketData, workspace: Workspace, engine: Optional[ForecastEngine] = None
) -> List[Tool]:
    """Инструменты, которые рисуют графики PNG в папку charts/ рабочей папки."""
    from .. import charts

    engine = engine or ForecastEngine()

    def target(name: str) -> Any:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^\w-]+", "_", name, flags=re.UNICODE).strip("_")[:40] or "chart"
        return workspace.resolve(f"charts/{slug}-{stamp}.png")

    def relative(path: Any) -> str:
        return str(path.relative_to(workspace.root))

    def chart_market(
        source: str, symbol: str, history_days: int, horizon_days: int
    ) -> Dict[str, Any]:
        _check_horizon(horizon_days)
        if source == "file":
            dates, closes = parse_price_csv(workspace.read_table(symbol))
            currency, unit, title = "", "", f"Цена: {symbol}"
        else:
            series = market.history(source, symbol, history_days)
            dates, closes = series.dates, series.closes
            currency, unit = series.currency, series.unit
            title = f"{series.symbol} ({source}){', ' + currency if currency else ''}"
        forecast = engine.market_forecast(
            "csv" if source == "file" else source, symbol, dates, closes, horizon_days,
            record=False,
        )
        path = charts.price_forecast_chart(target(f"{symbol}"), title, dates, closes, forecast,
                                           unit)
        return {"chart": relative(path), "last_price": closes[-1], "forecast_median":
                forecast["median"], "note": "График сохранён; покажите пользователю путь к файлу."}

    def chart_cashflow(path: str, opening_balance: float, horizon_days: int) -> Dict[str, Any]:
        _check_horizon(horizon_days)
        statement = read_statement(workspace, path)
        transactions = statement.transactions
        opening_balance = opening_for(statement, opening_balance)
        analysis = analyze_cashflow(transactions, opening_balance, horizon_days)
        engine.cashflow_forecast(analysis, transactions, path, record=False)
        balance = charts.cashflow_forecast_chart(
            target("balance"), transactions, opening_balance, analysis["forecast"]
        )
        monthly = charts.monthly_flows_chart(target("monthly"), analysis["monthly"])
        return {"charts": [relative(balance), relative(monthly)],
                "note": "Графики сохранены; покажите пользователю пути к файлам."}

    return [
        Tool(
            name="chart_market",
            description=(
                "Рисует график PNG: история цены и прогноз с интервалами 80% и 95% "
                "(тем же методом и с той же калибровкой, что analyze_market). source: "
                "yahoo, moex, cbr - как в analyze_market; file - symbol это путь к CSV или "
                "Excel с ценами в рабочей папке. Сохраняет в charts/."
            ),
            input_schema=make_schema({
                "source": {"type": "string", "enum": [*SOURCES, "file"]},
                "symbol": {"type": "string", "description": "Тикер, код или путь к файлу"},
                "history_days": {"type": "integer", "description": "Дней истории на графике"},
                "horizon_days": {"type": "integer", "description": "Горизонт прогноза в днях"},
            }),
            handler=chart_market,
        ),
        Tool(
            name="chart_cashflow",
            description=(
                "Рисует два графика PNG по выписке (1С, CSV или Excel): остаток денег по дням с "
                "прогнозом и линией нуля, и поступления/расходы по месяцам. Сохраняет в charts/."
            ),
            input_schema=make_schema({
                "path": {"type": "string", "description": "Путь к выписке в рабочей папке"},
                "opening_balance": {"type": "number", "description": "Остаток на начало"},
                "horizon_days": {"type": "integer", "description": "Горизонт прогноза в днях"},
            }),
            handler=chart_cashflow,
        ),
    ]


def calendar_tools(workspace: Workspace, calendar: Any) -> List[Tool]:
    """Платёжный календарь: плановые платежи и прогноз остатка по дням."""
    from datetime import date as _date

    from ..payment_calendar import parse_repeat, project

    def payment_calendar(path: str, opening_balance: float, horizon_days: int) -> Dict[str, Any]:
        statement = read_statement(workspace, path)
        planned = calendar.list()
        result = project(statement.transactions, opening_for(statement, opening_balance),
                         planned, horizon_days)
        # Для модели - только дни с платежами и рискованные дни, чтобы не раздувать ответ.
        result["days"] = [d for d in result["days"]
                          if d["planned"] or d["probability_negative"] >= 0.2]
        result["planned_payments"] = [p.as_dict() for p in planned]
        result["note"] = (
            "expected - ожидаемый остаток на конец дня; low_80/high_80 - интервал 80%; "
            "gap - первый день, когда ожидаемый остаток уходит в минус, shortfall - "
            "сколько не хватит в худшей точке, movable - крупные плановые платежи до "
            "разрыва, которые можно попробовать перенести."
        )
        return result

    def plan_payment(title: str, amount: float, due_date: str, repeat: str,
                     until: str) -> Dict[str, Any]:
        payment = calendar.add(
            title, amount, parse_date(due_date), parse_repeat(repeat),
            parse_date(until) if until.strip() else None,
        )
        return {"added": payment.as_dict()}

    def list_planned() -> Dict[str, Any]:
        today = _date.today()
        return {"today": today.isoformat(),
                "planned_payments": [p.as_dict() for p in calendar.list()]}

    def remove_planned(payment_id: int) -> str:
        if not calendar.remove(payment_id):
            raise ValueError(f"Нет планового платежа #{payment_id}")
        return f"Плановый платёж #{payment_id} удалён"

    return [
        Tool(
            name="payment_calendar",
            description=(
                "Платёжный календарь: прогноз остатка по дням с учётом плановых платежей "
                "(аренда, зарплата, налоги, счета, ожидаемые оплаты клиентов) и фонового "
                "потока из выписки. Находит день кассового разрыва, сколько не хватит и "
                "какие платежи можно перенести. Выписка - 1С, CSV или Excel в рабочей папке."
            ),
            input_schema=make_schema({
                "path": {"type": "string", "description": "Выписка в рабочей папке"},
                "opening_balance": {"type": "number",
                                    "description": "Остаток на начало выписки; 0 - из выписки"},
                "horizon_days": {"type": "integer", "description": "На сколько дней вперёд"},
            }),
            handler=payment_calendar,
            untrusted=True,
        ),
        Tool(
            name="plan_payment",
            description=(
                "Добавляет плановый платёж или ожидаемое поступление в платёжный календарь. "
                "amount: платёж - отрицательный, поступление - положительный. due_date - "
                "ГГГГ-ММ-ДД или ДД.ММ.ГГГГ. repeat: разово, еженедельно, ежемесячно, "
                "ежеквартально. until - дата окончания повторов или ''. Пользователь "
                "подтверждает."
            ),
            input_schema=make_schema({
                "title": {"type": "string"},
                "amount": {"type": "number"},
                "due_date": {"type": "string"},
                "repeat": {"type": "string"},
                "until": {"type": "string"},
            }),
            handler=plan_payment,
            requires_approval=True,
        ),
        Tool(
            name="list_planned_payments",
            description="Плановые платежи и поступления в платёжном календаре.",
            input_schema=make_schema({}),
            handler=list_planned,
        ),
        Tool(
            name="remove_planned_payment",
            description="Удаляет плановый платёж по номеру. Пользователь подтверждает.",
            input_schema=make_schema({"payment_id": {"type": "integer"}}),
            handler=remove_planned,
            requires_approval=True,
        ),
    ]


def portfolio_tool(
    market: MarketData, workspace: Workspace, engine: Optional[ForecastEngine] = None,
    tinvest_token: Optional[str] = None,
) -> Tool:
    from ..portfolio import TInvestClient, analyze_portfolio, load_portfolio

    def handler(path: str, use_tinvest: bool, horizon_days: int) -> Dict[str, Any]:
        _check_horizon(horizon_days)
        if use_tinvest:
            positions = TInvestClient(tinvest_token or "").positions()
        else:
            positions = load_portfolio(workspace.resolve(path))
        return analyze_portfolio(positions, market, engine, horizon_days)

    return Tool(
        name="analyze_portfolio",
        description=(
            "Анализ инвестиционного портфеля: стоимость в рублях, доли бумаг и классов "
            "активов, годовая волатильность, VaR 95% (возможная потеря за день и месяц), "
            "максимальная просадка, стресс-тесты (акции РФ -20%, рубль ±, крипта -40%...), "
            "предупреждения о концентрации и прогноз по каждой бумаге. Позиции: файл CSV/Excel "
            "в рабочей папке (тикер, количество, необязательно источник moex/yahoo/cbr и цена "
            "покупки) или брокерский счёт T-Invest (use_tinvest=true, если задан токен)."
        ),
        input_schema=make_schema({
            "path": {"type": "string", "description": "Файл портфеля; '' при use_tinvest"},
            "use_tinvest": {"type": "boolean"},
            "horizon_days": {"type": "integer", "description": "Горизонт прогноза, обычно 30"},
        }),
        handler=handler,
        untrusted=True,
    )
