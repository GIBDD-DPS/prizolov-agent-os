# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Проверка живых источников данных: Yahoo, Мосбиржа, ЦБ, ЕИС, T-Invest.

Обычные тесты работают без сети, поэтому не заметят, если источник поменяет формат
ответа. Эти тесты ходят в сеть и запускаются только с PRIZOLOV_LIVE=1 (ночная задача
в CI):

    PRIZOLOV_LIVE=1 python -m pytest tests/test_live.py

Если источник недоступен из этой сети (нет связи, тайм-аут, блокировка, перегрузка),
тест пропускается с причиной: это не ошибка кода. Тест падает, когда источник
ответил, но ответ не удалось разобрать или он пустой - значит, пора чинить код.
"""

import os
import urllib.error
from datetime import date, timedelta
from typing import Optional

import pytest

from prizolov_os.market import MarketData, MarketDataError
from prizolov_os.portfolio import PortfolioError, TInvestClient
from prizolov_os.tenders import TenderSearch, TenderSearchError

live = pytest.mark.skipif(
    os.getenv("PRIZOLOV_LIVE") != "1", reason="живые источники: запуск с PRIZOLOV_LIVE=1"
)

# Коды HTTP, которые означают «нас не пустили или сервер занят», а не смену формата.
UNREACHABLE_CODES = {403, 429, 451, 500, 502, 503, 504}


def unreachable(error: BaseException, codes=UNREACHABLE_CODES) -> bool:
    """Ошибка сети или доступа (её причина - в цепочке исключений)."""
    seen: Optional[BaseException] = error
    while seen is not None:
        if isinstance(seen, urllib.error.HTTPError):
            return seen.code in codes
        if isinstance(seen, (urllib.error.URLError, TimeoutError, ConnectionError)):
            return True
        seen = seen.__cause__
    return False


def fetch_or_skip(call, errors, codes=UNREACHABLE_CODES):
    try:
        return call()
    except errors as e:
        if unreachable(e, codes):
            pytest.skip(f"Источник недоступен из этой сети: {e}")
        raise


@live
@pytest.mark.parametrize("source, symbol", [
    ("yahoo", "GC=F"),
    ("yahoo", "BTC-USD"),
    ("moex", "SBER"),
    ("cbr", "USD"),
    ("cbr", "GOLD"),
])
def test_market_history(source, symbol):
    series = fetch_or_skip(lambda: MarketData().history(source, symbol, 30), MarketDataError)
    assert len(series.closes) >= 10, f"{source} {symbol}: мало точек ({len(series.closes)})"
    assert len(series.dates) == len(series.closes)
    assert all(price > 0 for price in series.closes)
    assert series.dates == sorted(series.dates)
    # Данные свежие: последняя точка не старше недели (выходные и праздники).
    assert series.dates[-1] >= date.today() - timedelta(days=7), series.dates[-1]


@live
def test_tenders_rss():
    tenders = fetch_or_skip(
        lambda: TenderSearch().search("поставка мебели", limit=10), TenderSearchError
    )
    assert tenders, "ЕИС ответила, но в ленте нет закупок: изменился формат RSS?"
    for tender in tenders:
        assert tender.number and tender.title
        assert tender.url.startswith("https://zakupki.gov.ru/")
    assert any(t.price for t in tenders), "Ни у одной закупки не разобрана цена"


@live
@pytest.mark.skipif(not os.getenv("PRIZOLOV_TINVEST_TOKEN"),
                    reason="нет PRIZOLOV_TINVEST_TOKEN (токен только для чтения)")
def test_tinvest_accounts():
    client = TInvestClient(os.environ["PRIZOLOV_TINVEST_TOKEN"])
    # 401/403 у T-Invest - неверный токен: это ошибка настройки, а не сети.
    accounts = fetch_or_skip(client.accounts, PortfolioError, codes={429, 500, 502, 503, 504})
    assert isinstance(accounts, list)
    for account in accounts:
        assert account.get("id"), account


def _http_error(code):
    return urllib.error.HTTPError("https://example.org", code, "err", {}, None)


@pytest.mark.parametrize("cause, expected", [
    (urllib.error.URLError("Tunnel connection failed"), True),
    (TimeoutError("timed out"), True),
    (_http_error(503), True),
    (_http_error(404), False),
    (None, False),
])
def test_unreachable_classifies_errors(cause, expected):
    error = MarketDataError("сбой")
    error.__cause__ = cause
    assert unreachable(error) is expected


def test_token_rejection_is_not_skipped():
    error = PortfolioError("T-Invest API не принял токен")
    error.__cause__ = _http_error(403)
    with pytest.raises(PortfolioError):
        fetch_or_skip(lambda: (_ for _ in ()).throw(error), PortfolioError, codes={503})
