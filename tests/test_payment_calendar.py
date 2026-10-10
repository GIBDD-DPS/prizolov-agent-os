# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Выписки 1С, статьи расходов и платёжный календарь."""

import argparse
import io
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from rich.console import Console

from prizolov_os.analytics.cashflow import Transaction
from prizolov_os.analytics.categories import by_category, categorize
from prizolov_os.analytics.statements import decode_text, load_statement, parse_1c
from prizolov_os.config import settings
from prizolov_os.core.kernel import Kernel
from prizolov_os.llm import FakeLLMClient, tool_use_response
from prizolov_os.memory import Store
from prizolov_os.payment_calendar import PaymentCalendar, parse_repeat, project

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
OWN = "40702810900000012345"

STATEMENT_1C = f"""1CClientBankExchange
ВерсияФормата=1.03
Кодировка=Windows
РасчСчет={OWN}
СекцияРасчСчет
РасчСчет={OWN}
НачальныйОстаток=100000.00
КонечныйОстаток=135000.00
КонецРасчСчет
СекцияДокумент=Платежное поручение
Номер=1
Дата=01.09.2026
Сумма=50000.00
ПлательщикСчет=40702810000000000001
Плательщик=ООО Клиент
ПолучательСчет={OWN}
Получатель=ООО Мы
ДатаПоступило=02.09.2026
НазначениеПлатежа=Оплата по счету 7, в т.ч. НДС 20%
КонецДокумента
СекцияДокумент=Платежное поручение
Номер=2
Дата=03.09.2026
Сумма=15000.00
ПлательщикСчет={OWN}
Плательщик=ООО Мы
ПолучательСчет=40101810000000000002
Получатель=УФК по г. Москве
ДатаСписано=03.09.2026
НазначениеПлатежа=Единый налоговый платеж
КонецДокумента
КонецФайла
"""


class TestStatements:
    def test_parse_1c_direction_dates_and_balances(self):
        statement = parse_1c(STATEMENT_1C)
        assert statement.source_format == "1c"
        assert statement.accounts == [OWN]
        assert statement.opening_balance == 100000.0
        assert statement.closing_balance == 135000.0
        income, tax = statement.transactions
        assert income.amount == 50000.0 and income.date == date(2026, 9, 2)
        assert income.description.startswith("ООО Клиент:")
        assert tax.amount == -15000.0 and "УФК" in tax.description

    def test_decode_windows_and_dos(self, tmp_path):
        assert decode_text(STATEMENT_1C.encode("cp1251")).startswith("1CClientBankExchange")
        dos = STATEMENT_1C.replace("Кодировка=Windows", "Кодировка=DOS").encode("cp866")
        assert "Единый налоговый" in decode_text(dos)
        assert decode_text("дата;сумма".encode("utf-8-sig")) == "дата;сумма"

    def test_load_statement_detects_format(self, tmp_path):
        one_c = tmp_path / "kl_to_1c.txt"
        one_c.write_bytes(STATEMENT_1C.encode("cp1251"))
        assert load_statement(one_c).source_format == "1c"
        csv_file = tmp_path / "bank.csv"
        csv_file.write_bytes("дата;сумма;назначение\n01.09.2026;-100;Аренда\n".encode("cp1251"))
        statement = load_statement(csv_file)
        assert statement.transactions[0].description == "Аренда"
        assert statement.opening_balance is None

    def test_demo_1c_matches_demo_csv(self):
        one_c = load_statement(EXAMPLES / "demo_bank_statement_1c.txt")
        csv_statement = load_statement(EXAMPLES / "demo_bank_statement.csv")
        assert sum(t.amount for t in one_c.transactions) == pytest.approx(
            sum(t.amount for t in csv_statement.transactions))
        assert one_c.opening_balance == 3_000_000

    def test_errors(self, tmp_path):
        with pytest.raises(ValueError):
            parse_1c("не 1С")
        empty = STATEMENT_1C.split("СекцияДокумент")[0] + "КонецФайла\n"
        with pytest.raises(ValueError, match="нет операций"):
            parse_1c(empty)
        with pytest.raises(FileNotFoundError):
            load_statement(tmp_path / "нет.txt")


class TestCategories:
    @pytest.mark.parametrize("text, amount, expected", [
        ("ООО Поставка: Оплата за товар по счету 15, в т.ч. НДС 20%", -1, "Закупки у поставщиков"),
        ("ООО Х: Оплата услуг по сч. 3, без налога (НДС)", -1, "Прочие расходы"),
        ("УФК по г. Москве: Единый налоговый платеж", -1, "Налоги и взносы"),
        ("Сотрудники: Перечисление заработной платы по реестру", -1, "Зарплата"),
        ("ООО БЦ: Арендная плата за октябрь, в т.ч. НДС", -1, "Аренда"),
        ("ПАО Банк: Комиссия за обслуживание счета", -1, "Банковские услуги"),
        ("ООО Альфа: Оплата по договору, в том числе НДС 5000", 1, "Поступления от клиентов"),
        ("Перевод собственных средств", 1, "Переводы между своими счетами"),
        ("ООО Реклама: Оплата рекламы в интернете", -1, "Реклама и маркетинг"),
        ("ООО Хостинг: Оплата хостинга и интернета", -1, "Связь и ИТ"),
    ])
    def test_rules(self, text, amount, expected):
        assert categorize(Transaction(date(2026, 1, 1), amount, text)) == expected

    def test_by_category_sorted(self):
        rows = by_category([
            Transaction(date(2026, 1, 1), -100, "Аренда"),
            Transaction(date(2026, 1, 2), -900, "Заработная плата"),
            Transaction(date(2026, 1, 3), 50, "Оплата от клиента"),
        ])
        assert [r["category"] for r in rows] == ["Зарплата", "Аренда", "Поступления от клиентов"]
        assert rows[0]["outflow"] == 900 and rows[0]["count"] == 1


def history(days=60, daily_income=10_000.0, salary=-150_000.0):
    start = date(2026, 8, 1)
    rows = []
    for i in range(days):
        rows.append(Transaction(start + timedelta(i), daily_income, "Оплата от клиента"))
        if (start + timedelta(i)).day == 5:
            rows.append(Transaction(start + timedelta(i), salary, "Заработная плата"))
    return rows


class TestCalendar:
    def test_occurrences_month_end_and_until(self):
        calendar = PaymentCalendar(Store())
        rent = calendar.add("Аренда", -100, date(2026, 1, 31), "monthly", date(2026, 4, 30))
        dates = rent.occurrences(date(2026, 1, 1), date(2026, 12, 31))
        assert dates == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31),
                         date(2026, 4, 30)]
        weekly = calendar.add("Уборка", -10, date(2026, 1, 1), "weekly")
        assert len(weekly.occurrences(date(2026, 1, 1), date(2026, 1, 31))) == 5
        once = calendar.add("Счёт", -10, date(2026, 1, 10))
        assert once.occurrences(date(2026, 2, 1), date(2026, 3, 1)) == []
        assert rent.category == "Аренда" and once.repeat == ""

    def test_validation_and_remove(self):
        calendar = PaymentCalendar(Store())
        with pytest.raises(ValueError):
            calendar.add("", -1, date(2026, 1, 1))
        with pytest.raises(ValueError):
            calendar.add("X", 0, date(2026, 1, 1))
        with pytest.raises(ValueError):
            calendar.add("X", -1, date(2026, 1, 1), "daily")
        with pytest.raises(ValueError):
            calendar.add("X", -1, date(2026, 2, 1), "monthly", date(2026, 1, 1))
        payment = calendar.add("X", -1, date(2026, 1, 1))
        assert calendar.remove(payment.id) and not calendar.remove(payment.id)
        assert parse_repeat("Ежемесячно") == "monthly" and parse_repeat("") == ""
        with pytest.raises(ValueError):
            parse_repeat("ежечасно")

    def test_project_finds_gap_without_double_counting(self):
        transactions = history()
        calendar = PaymentCalendar(Store())
        salary = calendar.add("Заработная плата", -400_000, date(2026, 10, 5), "monthly")
        plan = project(transactions, 0.0, [salary], 30)
        # Зарплата из истории исключена из фона: фон = только поступления.
        assert plan["background_daily"] == pytest.approx(10_000.0)
        assert plan["start"] == "2026-09-30"
        gap = plan["gap"]
        assert gap is not None and gap["date"] == "2026-10-05"
        assert gap["movable"][0]["title"] == "Заработная плата"
        day = next(d for d in plan["days"] if d["date"] == "2026-10-05")
        assert day["planned"][0]["amount"] == -400_000

    def test_one_off_income_does_not_remove_background(self):
        transactions = history()
        calendar = PaymentCalendar(Store())
        one_off = calendar.add("Оплата от клиента", 50_000, date(2026, 10, 1))
        plan = project(transactions, 0.0, [one_off], 10)
        assert plan["background_daily"] > 0 and plan["gap"] is None

    def test_project_errors(self):
        with pytest.raises(ValueError):
            project([], 0, [], 10)
        with pytest.raises(ValueError):
            project(history(), 0, [], 0)


class TestCli:
    def test_calendar_and_cashflow_1c(self, tmp_path, monkeypatch):
        from cli.main import run_calendar, run_cashflow

        monkeypatch.setattr(settings, "db_path", str(tmp_path / "db.sqlite"))
        monkeypatch.setattr(settings, "workspace_dir", str(tmp_path / "ws"))

        def run(fn, **kw):
            out = io.StringIO()
            code = fn(Console(file=out, width=200, color_system=None), argparse.Namespace(**kw))
            return code, out.getvalue()

        code, out = run(run_calendar, action="add", title="Заработная плата", amount=-900_000,
                        date="2026-10-05", repeat="ежемесячно", until=None)
        assert code == 0 and "Зарплата" in out
        code, out = run(run_calendar, action=None)
        assert "Заработная плата" in out
        code, out = run(run_cashflow, file=str(EXAMPLES / "demo_bank_statement_1c.txt"),
                        balance=None, days=60)
        assert code == 0
        assert "выписка 1С, остаток на начало из файла" in out
        assert "По статьям" in out and "Налоги и взносы" in out
        assert "Кассовый разрыв" in out
        code, out = run(run_calendar, action="remove", id=99)
        assert code == 1


class TestAgentTools:
    def test_analyst_uses_1c_and_plans_payment(self, tmp_path):
        (tmp_path / "bank.txt").write_bytes(STATEMENT_1C.encode("cp1251"))
        store = Store()
        llm = FakeLLMClient([
            tool_use_response("delegate", {"agent": "cashflow_analyst", "task": "календарь"}),
            tool_use_response("analyze_cashflow", {"path": "bank.txt", "opening_balance": 0,
                                                   "horizon_days": 30}),
            tool_use_response("plan_payment", {"title": "Аренда", "amount": -200000,
                                               "due_date": "2026-09-10", "repeat": "ежемесячно",
                                               "until": ""}, tool_id="toolu_2"),
            tool_use_response("payment_calendar", {"path": "bank.txt", "opening_balance": 0,
                                                   "horizon_days": 30}, tool_id="toolu_3"),
            "Разрыв 10 сентября", "Итог",
        ])
        kernel = Kernel.create(llm=llm, store=store, self_check="off", workspace_dir=tmp_path,
                               approver=lambda tool, params: True)
        kernel.chat("Хватит ли денег?")
        results = [m for m in llm.calls[-2]["messages"] if m["role"] == "user"]
        text = json.dumps(results, ensure_ascii=False)
        assert "Налоги и взносы" in text and "Остаток на начало взят из выписки 1С" in text
        assert "shortfall" in text and "2026-09-10" in text
        assert PaymentCalendar(store).list()[0].title == "Аренда"
