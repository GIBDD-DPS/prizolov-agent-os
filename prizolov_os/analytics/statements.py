# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Загрузка банковских выписок: формат 1С (1CClientBankExchange), CSV и Excel.

Формат 1С выгружает почти любой российский клиент-банк («Экспорт в 1С»). Из него
берутся операции, начальный и конечный остаток; направление платежа определяется
по своему расчётному счёту.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .cashflow import Transaction, parse_amount, parse_cashflow_csv, parse_date

HEADER_1C = "1CClientBankExchange"
TABLE_SUFFIXES = {".xlsx", ".xlsm"}


@dataclass
class Statement:
    """Выписка: операции и, если известны, остатки и свои счета."""

    transactions: List[Transaction]
    opening_balance: Optional[float] = None
    closing_balance: Optional[float] = None
    accounts: List[str] = field(default_factory=list)
    source_format: str = "csv"


def decode_text(data: bytes) -> str:
    """Текст файла в UTF-8, Windows-1251 или DOS (cp866) - как выгружают банки."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    dos = data.decode("cp866", errors="replace")
    if "Кодировка=DOS" in dos[:2000]:
        return dos
    return data.decode("cp1251", errors="replace")


def is_1c(text: str) -> bool:
    return text.lstrip("﻿ \r\n").startswith(HEADER_1C)


def parse_1c(text: str) -> Statement:
    """Разбирает выписку в формате обмена 1С с клиент-банком."""
    if not is_1c(text):
        raise ValueError("Это не файл обмена 1С (нет строки 1CClientBankExchange)")
    accounts: List[str] = []
    opening: Optional[float] = None
    closing: Optional[float] = None
    documents: List[Dict[str, str]] = []
    current: Optional[Dict[str, str]] = None
    section = ""

    for raw in text.splitlines():
        line = raw.strip()
        if not line or "=" not in line:
            if line == "КонецДокумента" and current is not None:
                documents.append(current)
                current = None
            elif line.startswith("СекцияРасчСчет"):
                section = "account"
            elif line == "КонецРасчСчет":
                section = ""
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key == "СекцияДокумент":
            current = {"_kind": value}
            continue
        if current is not None:
            current[key] = value
        elif key == "РасчСчет" and value and value not in accounts:
            accounts.append(value)
        elif section == "account" and key == "НачальныйОстаток" and opening is None:
            opening = _amount(value)
        elif section == "account" and key == "КонечныйОстаток":
            closing = _amount(value)

    transactions = []
    for doc in documents:
        transaction = _transaction(doc, accounts)
        if transaction is not None:
            transactions.append(transaction)
    if not transactions:
        raise ValueError(
            f"В выписке 1С нет операций (документов: {len(documents)}). Проверьте, что "
            "выгружен нужный период и счёт."
        )
    return Statement(sorted(transactions, key=lambda t: t.date), opening, closing, accounts,
                     "1c")


def _amount(value: str) -> Optional[float]:
    try:
        return parse_amount(value)
    except ValueError:
        return None


def _transaction(doc: Dict[str, str], accounts: List[str]) -> Optional[Transaction]:
    amount = _amount(doc.get("Сумма", ""))
    if amount is None:
        return None
    payer_account = doc.get("ПлательщикСчет") or doc.get("ПлательщикРасчСчет", "")
    payee_account = doc.get("ПолучательСчет") or doc.get("ПолучательРасчСчет", "")
    if accounts and payer_account in accounts and payee_account in accounts:
        outgoing = None  # перевод между своими счетами внутри одной выписки
    elif accounts and payer_account in accounts:
        outgoing = True
    elif accounts and payee_account in accounts:
        outgoing = False
    elif doc.get("ДатаСписано"):
        outgoing = True
    elif doc.get("ДатаПоступило"):
        outgoing = False
    else:
        return None
    if outgoing is None:
        return None
    raw_date = (doc.get("ДатаСписано") if outgoing else doc.get("ДатаПоступило")) or doc.get(
        "Дата", ""
    )
    try:
        when = parse_date(raw_date)
    except ValueError:
        return None
    counterparty = doc.get("Получатель1" if outgoing else "Плательщик1") or doc.get(
        "Получатель" if outgoing else "Плательщик", ""
    )
    purpose = " ".join(doc.get("НазначениеПлатежа", "").split())
    description = f"{counterparty}: {purpose}" if counterparty and purpose else (
        counterparty or purpose
    )
    return Transaction(when, -amount if outgoing else amount, description)


def load_statement(path: Path) -> Statement:
    """Выписка из файла: 1С (.txt), CSV или Excel - формат определяется сам."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Файл '{path.name}' не найден")
    if path.suffix.lower() in TABLE_SUFFIXES:
        from ..documents import sheet_as_csv

        return Statement(parse_cashflow_csv(sheet_as_csv(path)), source_format="excel")
    text = decode_text(path.read_bytes())
    if is_1c(text):
        return parse_1c(text)
    return Statement(parse_cashflow_csv(text))


__all__ = ["Statement", "decode_text", "is_1c", "load_statement", "parse_1c"]
