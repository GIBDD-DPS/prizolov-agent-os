# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Госзакупки (44-ФЗ, 223-ФЗ): поиск закупок в ЕИС и учёт уже показанных.

Поиск идёт через RSS-ленту расширенного поиска zakupki.gov.ru - ту же, на которую
можно подписаться в браузере. Формат ленты задаёт площадка и может меняться; если
поиск перестал находить закупки, документацию можно загрузить вручную, и агент
разберёт её. С площадкой ЕИС нередко нет связи из-за рубежа.
"""

import html
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

from .__about__ import __version__
from .memory import Store

RSS_URL = "https://zakupki.gov.ru/epz/order/extendedsearch/rss.html"
USER_AGENT = (f"Mozilla/5.0 (compatible; Prizolov-Agent-OS/{__version__}; "
              "+https://prizolov.ru)")
MAX_RESULTS = 50

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenders_seen (
    number TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    first_seen TEXT NOT NULL
);
"""

Fetch = Callable[[str], bytes]


class TenderSearchError(RuntimeError):
    """Площадка недоступна или ответила не так, как ожидалось."""


@dataclass
class Tender:
    number: str
    title: str
    url: str
    law: str = ""
    customer: str = ""
    price: Optional[float] = None
    currency: str = ""
    stage: str = ""
    published: str = ""
    deadline: str = ""
    new: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_url(query: str, laws: Sequence[str] = ("44", "223"), min_price: float = 0,
              max_price: float = 0, only_open: bool = True, per_page: int = 20) -> str:
    params: Dict[str, str] = {
        "searchString": query,
        "morphology": "on",
        "sortBy": "UPDATE_DATE",
        "sortDirection": "false",
        "pageNumber": "1",
        "recordsPerPage": f"_{per_page}",
        "currencyIdGeneral": "-1",
    }
    if "44" in laws:
        params["fz44"] = "on"
    if "223" in laws:
        params["fz223"] = "on"
    if only_open:
        params["af"] = "on"  # этап «Подача заявок»
    if min_price:
        params["priceFromGeneral"] = str(int(min_price))
    if max_price:
        params["priceToGeneral"] = str(int(max_price))
    return f"{RSS_URL}?{urllib.parse.urlencode(params)}"


def _http_get(url: str) -> bytes:
    from .config import settings

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=settings.timeout) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        raise TenderSearchError(f"Площадка закупок ответила ошибкой {e.code}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise TenderSearchError(f"Нет связи с zakupki.gov.ru: {e}") from e


def _text(description: str) -> Dict[str, str]:
    """Поля из описания закупки: «Метка: значение» в HTML с <br/>."""
    text = re.sub(r"<br\s*/?>", "\n", description, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    fields: Dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            label, value = line.split(":", 1)
            label, value = " ".join(label.split()).lower(), " ".join(value.split())
            if label and value and label not in fields:
                fields[label] = value
    return fields


def _field(fields: Dict[str, str], *keys: str) -> str:
    for label, value in fields.items():
        if any(key in label for key in keys):
            return value
    return ""


def _price(value: str) -> Optional[float]:
    cleaned = re.sub(r"[^\d,.]", "", value.replace("\xa0", "")).replace(",", ".")
    if cleaned.count(".") > 1:
        head, tail = cleaned.rsplit(".", 1)
        cleaned = head.replace(".", "") + "." + tail
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def parse_rss(data: bytes) -> List[Tender]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise TenderSearchError(
            "Площадка вернула не RSS (возможно, изменился формат или нужна проверка "
            "«я не робот»)"
        ) from e
    tenders = []
    for item in root.iter("item"):
        title = " ".join((item.findtext("title") or "").split())
        link = (item.findtext("link") or "").strip()
        if link.startswith("/"):
            link = "https://zakupki.gov.ru" + link
        fields = _text(item.findtext("description") or "")
        number_match = re.search(r"\d{11,19}", title + " " + link)
        number = number_match.group(0) if number_match else link
        name = _field(fields, "наименование объекта закупки", "объект закупки",
                      "наименование закупки")
        price_text = _field(fields, "начальная", "цена")
        law = _field(fields, "размещение выполняется", "закон")
        tenders.append(Tender(
            number=number,
            title=name or title,
            url=link,
            law=law,
            customer=_field(fields, "заказчик", "организация, осуществляющая"),
            price=_price(price_text),
            currency=_field(fields, "валюта"),
            stage=_field(fields, "этап"),
            published=_field(fields, "размещено") or (item.findtext("pubDate") or "").strip(),
            deadline=_field(fields, "окончание подачи", "дата окончания"),
        ))
    return tenders


class TenderSearch:
    def __init__(self, store: Optional[Store] = None, fetch: Optional[Fetch] = None) -> None:
        self.store = store
        self.fetch = fetch or _http_get
        if store is not None:
            store.add_schema(SCHEMA)

    def search(
        self, query: str, laws: Sequence[str] = ("44", "223"), min_price: float = 0,
        max_price: float = 0, only_new: bool = False, limit: int = 20,
    ) -> List[Tender]:
        query = " ".join(query.split())
        if len(query) < 3:
            raise ValueError("Опишите, что ищете: например «поставка офисной мебели»")
        limit = max(1, min(limit, MAX_RESULTS))
        tenders = parse_rss(self.fetch(build_url(query, laws, min_price, max_price,
                                                 per_page=min(50, max(10, limit)))))
        if self.store is not None:
            tenders = self._mark_seen(tenders)
        if only_new:
            tenders = [t for t in tenders if t.new]
        return tenders[:limit]

    def _mark_seen(self, tenders: List[Tender]) -> List[Tender]:
        assert self.store is not None
        now = datetime.now(timezone.utc).isoformat()
        for tender in tenders:
            seen = self.store.query("SELECT 1 FROM tenders_seen WHERE number = ?",
                                    (tender.number,))
            tender.new = not seen
            if not seen:
                self.store.execute(
                    "INSERT OR IGNORE INTO tenders_seen (number, title, first_seen) "
                    "VALUES (?, ?, ?)", (tender.number, tender.title[:300], now),
                )
        return tenders


__all__ = ["Tender", "TenderSearch", "TenderSearchError", "build_url", "parse_rss"]
