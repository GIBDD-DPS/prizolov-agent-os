# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Портфель частного инвестора: состав, риск, стресс-тесты, прогнозы по бумагам.

Позиции берутся из CSV/Excel (тикер, количество) или из брокерского счёта через
T-Invest API (нужен токен только для чтения). Цены и история - из тех же
источников, что и у рыночного аналитика (Мосбиржа, Yahoo Finance, ЦБ РФ).
Это статистическая оценка, а не инвестиционная рекомендация.
"""

import json
import math
import statistics
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .__about__ import USER_AGENT
from .forecasting import ForecastEngine
from .forecasting.classify import ASSET_CLASSES, asset_class
from .market import CBR_CURRENCIES, CBR_METALS, MarketData, MarketDataError, PriceSeries

HISTORY_DAYS = 400
WINDOW = 250
TRADING_DAYS = 252
CONCENTRATION_WARN = 0.25
CLASS_WARN = 0.6
RUB = {"RUB", "SUR", "RUR", ""}

# Сценарии стресс-теста: изменение цены в рублях по классам активов.
SCENARIOS: List[Tuple[str, Dict[str, float]]] = [
    ("Российские акции -20%", {"stock_ru": -0.20}),
    ("Рубль ослаб на 20% (валютные активы +20% в рублях)", {"__foreign__": 0.20}),
    ("Рубль укрепился на 15%", {"__foreign__": -0.15}),
    ("Мировые акции -25%", {"stock": -0.25, "index": -0.25}),
    ("Криптовалюты -40%", {"crypto": -0.40}),
    ("Золото и металлы +15%", {"metal": 0.15}),
]

QUANTITY_COLUMNS = {"quantity", "количество", "кол-во", "qty", "шт", "штук", "лоты"}
TICKER_COLUMNS = {"ticker", "тикер", "symbol", "код", "инструмент", "secid"}
SOURCE_COLUMNS = {"source", "источник", "биржа"}
PRICE_COLUMNS = {"price", "цена", "цена покупки", "средняя цена", "avg price"}


class PortfolioError(ValueError):
    """Портфель не удалось загрузить или посчитать."""


@dataclass
class Position:
    symbol: str
    quantity: float
    source: str = ""
    avg_price: Optional[float] = None
    name: str = ""


@dataclass
class PositionValue:
    position: Position
    source: str
    currency: str
    price: float
    fx: float
    value_rub: float
    asset_class: str
    series: PriceSeries = field(repr=False)


def guess_source(symbol: str) -> str:
    """Мосбиржа для коротких латинских тикеров (SBER, GAZP), ЦБ для металлов и валют
    ЦБ, иначе Yahoo (AAPL, BTC-USD, GC=F)."""
    code = symbol.upper()
    if code in CBR_METALS or code in CBR_CURRENCIES:
        return "cbr"
    if code.isalpha() and code.isascii() and 3 <= len(code) <= 5 and code.isupper():
        return "moex"
    return "yahoo"


# --- Загрузка ----------------------------------------------------------------


def parse_portfolio_csv(text: str) -> List[Position]:
    """CSV с колонками тикер, количество[, источник, цена покупки]."""
    import csv
    import io

    from .analytics.cashflow import parse_amount

    text = text.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise PortfolioError("В файле нет позиций")
    header = [c.strip().lower() for c in rows[0]]

    def find(names: set) -> int:
        return next((i for i, h in enumerate(header) if h in names), -1)

    t_col, q_col, s_col, p_col = (find(TICKER_COLUMNS), find(QUANTITY_COLUMNS),
                                  find(SOURCE_COLUMNS), find(PRICE_COLUMNS))
    if t_col < 0 or q_col < 0:
        raise PortfolioError(
            f"Нужны колонки тикер и количество (ticker, quantity). Найдены: {', '.join(header)}"
        )
    positions = []
    for line_no, row in enumerate(rows[1:], start=2):
        try:
            symbol = row[t_col].strip().upper()
            quantity = parse_amount(row[q_col])
        except (IndexError, ValueError) as e:
            raise PortfolioError(f"Строка {line_no}: {e}") from None
        if not symbol or not quantity:
            continue
        source = row[s_col].strip().lower() if 0 <= s_col < len(row) else ""
        price = None
        if 0 <= p_col < len(row) and row[p_col].strip():
            try:
                price = parse_amount(row[p_col])
            except ValueError:
                price = None
        positions.append(Position(symbol, quantity, source, price))
    if not positions:
        raise PortfolioError("В файле нет позиций с ненулевым количеством")
    return positions


def load_portfolio(path: Path) -> List[Position]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Файл '{path.name}' не найден")
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from .documents import sheet_as_csv

        return parse_portfolio_csv(sheet_as_csv(path))
    from .analytics.statements import decode_text

    return parse_portfolio_csv(decode_text(path.read_bytes()))


# --- T-Invest API ------------------------------------------------------------

TINVEST_URL = "https://invest-public-api.tbank.ru/rest"
_SERVICE = "tinkoff.public.invest.api.contract.v1"
Post = Callable[[str, Dict[str, Any]], Dict[str, Any]]


def _money(value: Optional[Dict[str, Any]]) -> float:
    if not value:
        return 0.0
    return float(value.get("units", 0) or 0) + float(value.get("nano", 0) or 0) / 1e9


class TInvestClient:
    """Чтение портфеля из брокерского счёта Т-Банка (T-Invest API, REST).

    Нужен токен «только для чтения» (Т-Инвестиции → Настройки → Токены T-Invest API).
    """

    def __init__(self, token: str, base_url: str = TINVEST_URL, post: Optional[Post] = None):
        if not token:
            raise PortfolioError("Нет токена T-Invest API (PRIZOLOV_TINVEST_TOKEN)")
        self.token = token
        self.base_url = base_url.rstrip("/")
        self._post = post or self._http_post

    def _http_post(self, method: str, body: Dict[str, Any]) -> Dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/{_SERVICE}.{method}",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                     "User-Agent": USER_AGENT},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data: Dict[str, Any] = json.loads(response.read())
                return data
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise PortfolioError("T-Invest API не принял токен: проверьте его") from e
            raise PortfolioError(f"T-Invest API ответил ошибкой {e.code}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise PortfolioError(f"Нет связи с T-Invest API: {e}") from e

    def accounts(self) -> List[Dict[str, Any]]:
        accounts: List[Dict[str, Any]] = self._post("UsersService/GetAccounts", {}).get(
            "accounts", [])
        return accounts

    def positions(self, account_id: Optional[str] = None) -> List[Position]:
        if not account_id:
            accounts = [a for a in self.accounts() if a.get("status", "") in (
                "", "ACCOUNT_STATUS_OPEN")]
            if not accounts:
                raise PortfolioError("В T-Invest нет открытых счетов")
            account_id = accounts[0]["id"]
        portfolio = self._post("OperationsService/GetPortfolio",
                               {"accountId": account_id, "currency": "RUB"})
        result = []
        for item in portfolio.get("positions", []):
            kind = item.get("instrumentType", "")
            if kind == "currency":
                continue  # денежные остатки - не бумаги
            ticker = item.get("ticker") or self._ticker(item.get("figi", ""))
            quantity = _money(item.get("quantity"))
            if not ticker or not quantity:
                continue
            source = "moex" if kind in ("share", "etf", "bond") else ""
            result.append(Position(ticker.upper(), quantity, source,
                                   _money(item.get("averagePositionPrice")) or None))
        return result

    def _ticker(self, figi: str) -> str:
        if not figi:
            return ""
        data = self._post("InstrumentsService/GetInstrumentBy",
                          {"idType": "INSTRUMENT_ID_TYPE_FIGI", "id": figi})
        return str(data.get("instrument", {}).get("ticker", ""))


# --- Анализ ------------------------------------------------------------------


def _fx(market: MarketData, currency: str, cache: Dict[str, float]) -> float:
    code = currency.upper()
    if code in RUB:
        return 1.0
    if code not in cache:
        if code not in CBR_CURRENCIES:
            raise PortfolioError(f"Нет курса ЦБ для валюты {code}")
        cache[code] = market.history("cbr", code, 14).closes[-1]
    return cache[code]


def value_positions(positions: Sequence[Position], market: MarketData) -> Tuple[
        List[PositionValue], List[str]]:
    """Цены, валюта и стоимость в рублях; ошибки по отдельным бумагам - в списке."""
    values: List[PositionValue] = []
    errors: List[str] = []
    fx_cache: Dict[str, float] = {}
    for position in positions:
        source = position.source or guess_source(position.symbol)
        try:
            try:
                series = market.history(source, position.symbol, HISTORY_DAYS)
            except MarketDataError:
                if position.source or source != "moex":
                    raise
                # SBER и AAPL по виду не различить: не нашли на Мосбирже - ищем на Yahoo.
                source = "yahoo"
                series = market.history(source, position.symbol, HISTORY_DAYS)
            currency = series.currency or "RUB"
            if source == "cbr" and position.symbol.upper() in CBR_CURRENCIES:
                currency = "RUB"  # курс ЦБ уже в рублях за единицу валюты
            fx = _fx(market, currency, fx_cache)
        except (MarketDataError, PortfolioError) as e:
            errors.append(f"{position.symbol}: {e}")
            continue
        price = series.closes[-1]
        values.append(PositionValue(
            position, source, currency, price, fx, position.quantity * price * fx,
            asset_class(source, position.symbol), series,
        ))
    return values, errors


def _returns(values: Sequence[PositionValue]) -> Tuple[List[date], List[float]]:
    """Дневная доходность портфеля при текущем составе (общие даты всех бумаг)."""
    common = None
    maps = []
    for v in values:
        prices = dict(zip(v.series.dates, v.series.closes))
        maps.append(prices)
        common = set(prices) if common is None else common & set(prices)
    dates = sorted(common or [])[-(WINDOW + 1):]
    portfolio = [sum(v.position.quantity * m[d] * v.fx for v, m in zip(values, maps))
                 for d in dates]
    returns = [math.log(b / a) for a, b in zip(portfolio, portfolio[1:]) if a > 0 and b > 0]
    return dates, returns


def _drawdown(levels: Sequence[float]) -> float:
    peak, worst = levels[0] if levels else 0.0, 0.0
    for level in levels:
        peak = max(peak, level)
        if peak > 0:
            worst = min(worst, level / peak - 1)
    return worst


def analyze_portfolio(
    positions: Sequence[Position],
    market: MarketData,
    engine: Optional[ForecastEngine] = None,
    horizon_days: int = 30,
) -> Dict[str, Any]:
    if not positions:
        raise PortfolioError("Портфель пуст")
    values, errors = value_positions(positions, market)
    if not values:
        raise PortfolioError("Не удалось получить цены ни по одной бумаге: " + "; ".join(errors))
    total = sum(v.value_rub for v in values)
    if total <= 0:
        raise PortfolioError("Стоимость портфеля не положительная")
    engine = engine or ForecastEngine()

    rows: List[Dict[str, Any]] = []
    by_class: Dict[str, float] = {}
    for v in sorted(values, key=lambda x: -x.value_rub):
        weight = v.value_rub / total
        by_class[v.asset_class] = by_class.get(v.asset_class, 0.0) + weight
        closes = v.series.closes[-WINDOW - 1:]
        rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
        vol = statistics.stdev(rets) * math.sqrt(TRADING_DAYS) * 100 if len(rets) > 2 else None
        forecast = engine.market_forecast(v.source, v.position.symbol, v.series.dates,
                                          v.series.closes, horizon_days, record=False)
        cost = v.position.avg_price
        rows.append({
            "symbol": v.position.symbol, "source": v.source, "quantity": v.position.quantity,
            "price": round(v.price, 4), "currency": v.currency,
            "value_rub": round(v.value_rub, 2), "weight_pct": round(weight * 100, 2),
            "asset_class": ASSET_CLASSES.get(v.asset_class, v.asset_class),
            "volatility_pct": round(vol, 1) if vol is not None else None,
            "profit_pct": round((v.price / cost - 1) * 100, 2) if cost else None,
            "forecast": {
                "horizon_days": horizon_days,
                "median": round(forecast["median"], 4),
                "low_80": round(forecast["low_80"], 4),
                "high_80": round(forecast["high_80"], 4),
                "probability_up_pct": round(forecast["probability_up"] * 100),
                "method": forecast.get("method_name", ""),
            },
        })

    dates, returns = _returns(values)
    risk: Dict[str, Any] = {"observations": len(returns)}
    if len(returns) > 20:
        sd = statistics.stdev(returns)
        level = [1.0]
        for r in returns:
            level.append(level[-1] * math.exp(r))
        ordered = sorted(returns)
        var_1d = -ordered[max(int(len(ordered) * 0.05) - 1, 0)]
        risk.update({
            "volatility_annual_pct": round(sd * math.sqrt(TRADING_DAYS) * 100, 1),
            "var95_1d_rub": round(total * (1 - math.exp(-var_1d)), 2),
            "var95_1m_rub": round(total * (1 - math.exp(-1.645 * sd * math.sqrt(21))), 2),
            "max_drawdown_pct": round(_drawdown(level) * 100, 1),
            "period": f"{dates[0]} – {dates[-1]}" if dates else "",
        })

    stress = []
    for name, shocks in SCENARIOS:
        change = 0.0
        for v in values:
            shock = shocks.get(v.asset_class, 0.0)
            if "__foreign__" in shocks and v.currency.upper() not in RUB:
                shock += shocks["__foreign__"]
            change += v.value_rub * shock
        if change:
            stress.append({"scenario": name, "change_rub": round(change, 2),
                           "change_pct": round(change / total * 100, 2)})

    warnings = [f"{r['symbol']} - {r['weight_pct']}% портфеля: высокая концентрация"
                for r in rows if r["weight_pct"] >= CONCENTRATION_WARN * 100]
    warnings += [f"{ASSET_CLASSES.get(k, k)} - {round(w * 100, 1)}% портфеля: мало "
                 "диверсификации" for k, w in by_class.items() if w >= CLASS_WARN
                 and len(by_class) > 0 and len(values) > 1]
    return {
        "total_rub": round(total, 2),
        "positions": rows,
        "by_class": [{"asset_class": ASSET_CLASSES.get(k, k), "weight_pct": round(w * 100, 2)}
                     for k, w in sorted(by_class.items(), key=lambda kv: -kv[1])],
        "risk": risk,
        "stress": stress,
        "warnings": warnings,
        "errors": errors,
        "note": ("Риск и стресс-тест - по текущему составу и истории цен; прогнозы - "
                 "статистическая оценка, а не инвестиционная рекомендация."),
    }


__all__ = [
    "Position", "PortfolioError", "SCENARIOS", "TInvestClient", "analyze_portfolio",
    "guess_source", "load_portfolio", "parse_portfolio_csv",
]
