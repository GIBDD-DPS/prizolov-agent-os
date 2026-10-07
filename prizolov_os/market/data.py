"""Загрузка истории цен: Yahoo Finance, Московская биржа (ISS), ЦБ РФ.

Все источники бесплатные и не требуют ключей. HTTP-запрос вынесен в функцию
fetch, чтобы его можно было подменить в тестах.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Tuple

Fetch = Callable[[str], bytes]

USER_AGENT = "Mozilla/5.0 (compatible; prizolov-os)"

# Коды валют ЦБ РФ (VAL_NM_RQ) и номиналы котировок.
CBR_CURRENCIES: Dict[str, str] = {
    "USD": "R01235", "EUR": "R01239", "CNY": "R01375", "GBP": "R01035",
    "CHF": "R01775", "JPY": "R01820", "TRY": "R01700J", "KZT": "R01335",
    "BYN": "R01090B", "AED": "R01230", "INR": "R01270", "HKD": "R01200",
}
# Коды драгметаллов ЦБ РФ; цены в рублях за грамм.
CBR_METALS: Dict[str, str] = {"GOLD": "1", "SILVER": "2", "PLATINUM": "3", "PALLADIUM": "4"}
MOEX_BOARDS = ("TQBR", "TQTF")
SOURCES = ("yahoo", "moex", "cbr")


class MarketDataError(Exception):
    """Не удалось получить котировки."""


@dataclass
class PriceSeries:
    """История цен закрытия."""

    source: str
    symbol: str
    currency: str
    dates: List[date] = field(default_factory=list)
    closes: List[float] = field(default_factory=list)
    unit: str = ""


def http_get(url: str, timeout: float = 20.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        raise MarketDataError(f"Источник ответил ошибкой {e.code}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise MarketDataError(f"Нет связи с источником данных: {e}") from e


class MarketData:
    """Единая точка доступа к котировкам."""

    def __init__(self, fetch: Fetch = http_get, today: Optional[Callable[[], date]] = None):
        self._fetch = fetch
        self._today = today or date.today

    def history(self, source: str, symbol: str, days: int) -> PriceSeries:
        """История за последние days календарных дней."""
        if days < 5:
            raise MarketDataError("Период должен быть не меньше 5 дней")
        end = self._today()
        start = end - timedelta(days=days)
        symbol = symbol.strip()
        if source == "yahoo":
            series = self._yahoo(symbol, start, end)
        elif source == "moex":
            series = self._moex(symbol.upper(), start, end)
        elif source == "cbr":
            series = self._cbr(symbol.upper(), start, end)
        else:
            raise MarketDataError(f"Неизвестный источник '{source}'. Доступны: {SOURCES}")
        if len(series.closes) < 3:
            raise MarketDataError(
                f"Слишком мало данных по '{symbol}' в источнике {source}: "
                "проверьте тикер или увеличьте период"
            )
        return series

    def _json(self, url: str) -> dict:
        try:
            return json.loads(self._fetch(url))
        except json.JSONDecodeError as e:
            raise MarketDataError("Источник вернул некорректный ответ") from e

    def _yahoo(self, symbol: str, start: date, end: date) -> PriceSeries:
        params = urllib.parse.urlencode({
            "period1": _timestamp(start),
            "period2": _timestamp(end + timedelta(days=1)),
            "interval": "1d",
        })
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{urllib.parse.quote(symbol, safe='')}?{params}"
        )
        chart = self._json(url).get("chart") or {}
        if chart.get("error"):
            message = chart["error"].get("description") or chart["error"]
            raise MarketDataError(f"Yahoo: {message}")
        results = chart.get("result") or []
        if not results:
            raise MarketDataError(f"Yahoo не нашёл тикер '{symbol}'")
        result = results[0]
        closes = (result.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
        pairs = [
            (datetime.fromtimestamp(ts, tz=timezone.utc).date(), float(close))
            for ts, close in zip(result.get("timestamp") or [], closes)
            if close is not None
        ]
        return _series("yahoo", symbol, result.get("meta", {}).get("currency", ""), pairs)

    def _moex(self, secid: str, start: date, end: date) -> PriceSeries:
        for board in MOEX_BOARDS:
            pairs = self._moex_board(secid, board, start, end)
            if pairs:
                return _series("moex", secid, "RUB", pairs)
        return _series("moex", secid, "RUB", [])

    def _moex_board(
        self, secid: str, board: str, start: date, end: date
    ) -> List[Tuple[date, float]]:
        pairs: List[Tuple[date, float]] = []
        offset = 0
        while True:
            params = urllib.parse.urlencode({
                "from": start.isoformat(), "till": end.isoformat(), "start": offset,
                "iss.meta": "off", "history.columns": "TRADEDATE,CLOSE",
            })
            url = (
                f"https://iss.moex.com/iss/history/engines/stock/markets/shares/boards/{board}/"
                f"securities/{urllib.parse.quote(secid)}.json?{params}"
            )
            data = self._json(url)
            rows = (data.get("history") or {}).get("data") or []
            pairs.extend(
                (date.fromisoformat(day), float(close)) for day, close in rows if close is not None
            )
            cursor = ((data.get("history.cursor") or {}).get("data") or [[0, 0, 0]])[0]
            total = cursor[1]
            offset += len(rows)
            if not rows or offset >= total:
                return pairs

    def _cbr(self, code: str, start: date, end: date) -> PriceSeries:
        period = (
            f"date_req1={start.strftime('%d/%m/%Y')}&date_req2={end.strftime('%d/%m/%Y')}"
        )
        if code in CBR_METALS:
            root = self._xml(f"https://www.cbr.ru/scripts/xml_metall.asp?{period}")
            pairs = [
                (_cbr_date(r.get("Date", "")), _cbr_number(r.findtext("Buy", "")))
                for r in root.iter("Record")
                if r.get("Code") == CBR_METALS[code]
            ]
            return _series("cbr", code, "RUB", pairs, unit="руб. за грамм")
        if code in CBR_CURRENCIES:
            root = self._xml(
                f"https://www.cbr.ru/scripts/XML_dynamic.asp?{period}"
                f"&VAL_NM_RQ={CBR_CURRENCIES[code]}"
            )
            pairs = [
                (
                    _cbr_date(r.get("Date", "")),
                    _cbr_number(r.findtext("Value", "")) / _cbr_number(r.findtext("Nominal", "1")),
                )
                for r in root.iter("Record")
            ]
            return _series("cbr", code, "RUB", pairs, unit=f"руб. за 1 {code}")
        known = ", ".join([*CBR_CURRENCIES, *CBR_METALS])
        raise MarketDataError(f"ЦБ РФ: неизвестный код '{code}'. Доступны: {known}")

    def _xml(self, url: str) -> ET.Element:
        try:
            return ET.fromstring(self._fetch(url))
        except ET.ParseError as e:
            raise MarketDataError("ЦБ РФ вернул некорректный ответ") from e


def _series(
    source: str, symbol: str, currency: str, pairs: List[Tuple[date, float]], unit: str = ""
) -> PriceSeries:
    # Убираем дубли дат (оставляем последнее значение) и сортируем.
    by_date = dict(sorted(pairs))
    return PriceSeries(
        source, symbol, currency, list(by_date), list(by_date.values()), unit
    )


def _timestamp(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())


def _cbr_date(value: str) -> date:
    return datetime.strptime(value, "%d.%m.%Y").date()


def _cbr_number(value: str) -> float:
    return float(value.replace(",", ".").replace(" ", ""))
