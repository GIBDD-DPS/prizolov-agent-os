# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Статьи движения денег по назначению платежа (без участия модели).

Правила - по ключевым словам в назначении и названии контрагента. Порядок важен:
первое совпадение выигрывает. Что не распознано - «Прочие расходы» или
«Поступления от клиентов».
"""

import re
from collections import defaultdict
from typing import Any, Dict, List, Sequence, Tuple

from .cashflow import Transaction

# Упоминания НДС в назначении обычного платежа («в т.ч. НДС 20%», «без НДС») - не налог.
_VAT_MENTIONS = re.compile(
    r"(в\s*т\.?\s*ч\.?|в\s+том\s+числе|без)\s*(налога)?\s*\(?\s*ндс\s*\)?[^,;]*"
    r"|ндс\s+не\s+облага\w*|сумма\s+ндс[^,;]*|ндс\s*\(?\d+\s*%?\)?[^,;]*",
)

OTHER_EXPENSE = "Прочие расходы"
CUSTOMER_INCOME = "Поступления от клиентов"

# (статья, ключевые слова, для каких операций: out, in или any)
RULES: List[Tuple[str, Tuple[str, ...], str]] = [
    ("Переводы между своими счетами", (
        "собственных средств", "между своими счетами", "перевод средств на счет",
        "перевод денежных средств на собственный",
    ), "any"),
    ("Налоги и взносы", (
        "налог", "ндфл", "ндс", "енп", "единый налоговый", "страховые взносы", "взнос",
        "уфк", "фнс", "казначейств", "пени", "госпошлин",
    ), "out"),
    ("Зарплата", (
        "заработн", "зарплат", "з/п", "з/пл", "аванс сотрудник", "отпускн", "премия",
        "реестр", "выплаты сотрудникам",
    ), "out"),
    ("Аренда", ("аренд",), "out"),
    ("Кредиты и проценты", (
        "погашение кредит", "погашение основного долга", "уплата процент", "проценты по кредит",
        "по кредитному договору", "погашение займ", "лизинг",
    ), "out"),
    ("Получение кредитов и займов", (
        "выдача кредит", "предоставление кредит", "кредитные средства", "по договору займа",
        "получение займ",
    ), "in"),
    ("Банковские услуги", (
        "комисси", "обслуживание счет", "обслуживание р/с", "эквайринг", "тариф банк",
    ), "out"),
    ("Реклама и маркетинг", (
        "реклам", "маркетинг", "продвижен", "яндекс.директ", "яндекс директ", "таргет",
    ), "out"),
    ("Связь и ИТ", (
        "связь", "услуги связи", "интернет", "хостинг", "телефон", "программн", "лиценз", "подписк",
        "облачн", "сервер", "домен",
    ), "out"),
    ("Коммунальные услуги", (
        "электроэнерг", "коммунал", "водоснабж", "теплоснабж", "отоплен", "вывоз мусора",
    ), "out"),
    ("Логистика и транспорт", (
        "доставк", "транспортн", "перевозк", "логист", "топлив", "бензин", "гсм",
    ), "out"),
    ("Закупки у поставщиков", (
        "закупк", "поставк", "товар", "материал", "комплектующ", "сырь",
    ), "out"),
    ("Возвраты", ("возврат",), "any"),
]


def categorize(transaction: Transaction) -> str:
    text = _VAT_MENTIONS.sub(" ", transaction.description.lower())
    direction = "out" if transaction.amount < 0 else "in"
    for category, words, applies in RULES:
        if applies not in ("any", direction):
            continue
        if any(word in text for word in words):
            return category
    return OTHER_EXPENSE if direction == "out" else CUSTOMER_INCOME


def by_category(transactions: Sequence[Transaction]) -> List[Dict[str, Any]]:
    """Итоги по статьям: поступления и расходы, число операций; крупные - выше."""
    totals: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"inflow": 0.0, "outflow": 0.0, "count": 0}
    )
    for t in transactions:
        bucket = totals[categorize(t)]
        bucket["inflow" if t.amount > 0 else "outflow"] += abs(t.amount)
        bucket["count"] += 1
    rows = [
        {"category": name, "inflow": round(v["inflow"], 2), "outflow": round(v["outflow"], 2),
         "count": int(v["count"])}
        for name, v in totals.items()
    ]
    return sorted(rows, key=lambda r: -(r["inflow"] + r["outflow"]))


__all__ = ["CUSTOMER_INCOME", "OTHER_EXPENSE", "RULES", "by_category", "categorize"]
