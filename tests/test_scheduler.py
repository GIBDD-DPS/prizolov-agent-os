# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Тесты расписания задач."""

import io
import json
from datetime import datetime, timedelta, timezone

import pytest
from rich.console import Console

from cli.app import ChatApp
from prizolov_os.__about__ import SIGNATURE
from prizolov_os.core.kernel import Kernel
from prizolov_os.llm import FakeLLMClient, tool_use_response
from prizolov_os.memory import Store
from prizolov_os.scheduler import (
    CronSpec,
    ScheduleError,
    ScheduleRunner,
    ScheduleStore,
    describe,
    next_run,
    report_payload,
    to_cron,
)
from tests.test_reports import StubMarket

NOW = datetime(2026, 10, 8, 20, 0, tzinfo=timezone.utc)  # четверг, 23:00 по Москве


class TestParsing:
    @pytest.mark.parametrize("text, cron", [
        ("ежедневно 09:00", "0 9 * * *"),
        ("каждый день 7.05", "5 7 * * *"),
        ("по будням 9:30", "30 9 * * 1-5"),
        ("по выходным 11:00", "0 11 * * 0,6"),
        ("по понедельникам 10:00", "0 10 * * 1"),
        ("по средам и пятницам 18:15", "15 18 * * 3,5"),
        ("каждые 6 часов", "0 */6 * * *"),
        ("каждый час", "0 * * * *"),
        ("каждые 30 минут", "*/30 * * * *"),
        ("daily 08:00", "0 8 * * *"),
        ("weekly mon 10:00", "0 10 * * 1"),
        ("0 9 * * 1-5", "0 9 * * 1-5"),
    ])
    def test_to_cron(self, text, cron):
        assert to_cron(text) == cron

    @pytest.mark.parametrize("text", [
        "когда-нибудь", "каждые 5 минут", "каждые 7 часов", "ежедневно 25:00", "61 * * * *",
    ])
    def test_rejects(self, text):
        with pytest.raises(ScheduleError):
            to_cron(text)

    def test_next_run_in_moscow_time(self):
        assert next_run("0 9 * * *", NOW, "Europe/Moscow") == datetime(
            2026, 10, 9, 6, 0, tzinfo=timezone.utc
        )
        assert next_run("0 10 * * 1", NOW, "Europe/Moscow").date().isoformat() == "2026-10-12"

    def test_cron_day_or_weekday(self):
        spec = CronSpec("0 9 1 * 1")  # 1-е число ИЛИ понедельник, как в cron
        assert spec.matches(datetime(2026, 10, 1, 9, 0))  # четверг, 1-е
        assert spec.matches(datetime(2026, 10, 5, 9, 0))  # понедельник
        assert not spec.matches(datetime(2026, 10, 6, 9, 0))

    def test_describe(self):
        assert describe("30 9 * * 1-5") == "по будням 09:30"
        assert describe("0 10 * * 1,3") == "пн, ср 10:00"
        assert describe("*/30 * * * *") == "каждые 30 мин."


@pytest.fixture
def schedules():
    return ScheduleStore(Store(), "Europe/Moscow")


class TestStore:
    def test_add_list_due_and_no_catch_up(self, schedules):
        task = schedules.add("ежедневно 09:00", "task", "Обзор рынка", chat_id=5, now=NOW)
        assert task.next_run == datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc)
        assert schedules.due(NOW) == []
        later = NOW + timedelta(days=3)  # процесс был выключен три дня
        assert [t.id for t in schedules.due(later)] == [task.id]
        schedules.mark_run(task, "ok", "", later)
        assert schedules.get(task.id).next_run > later
        assert schedules.due(later) == []

    def test_pause_remove_builtin(self, schedules):
        schedules.ensure_builtin()
        schedules.ensure_builtin()
        builtin = [t for t in schedules.list() if t.builtin]
        assert len(builtin) == 1 and builtin[0].kind == "verify"
        with pytest.raises(ScheduleError):
            schedules.remove(builtin[0].id)
        schedules.set_enabled(builtin[0].id, False)
        assert schedules.due(NOW + timedelta(days=2)) == []

    def test_chat_filter_and_validation(self, schedules):
        schedules.add("ежедневно 09:00", "task", "a", chat_id=1)
        schedules.add("ежедневно 09:00", "task", "b", chat_id=2)
        assert [t.payload for t in schedules.list(chat_id=1)] == ["a"]
        with pytest.raises(ScheduleError):
            schedules.add("ежедневно 09:00", "task", " ")
        with pytest.raises(ScheduleError):
            schedules.add("ежедневно 09:00", "hack", "x")

    def test_report_title(self, schedules):
        task = schedules.add("по будням 9:00", "report", report_payload("gold", [30, 1, 7]))
        assert task.title == "Отчёт GOLD (1, 7, 30 дн.)"


def make_kernel(tmp_path, responses=(), store=None):
    return Kernel.create(llm=FakeLLMClient(list(responses)), store=store or Store(),
                         workspace_dir=tmp_path, self_check="off", market=StubMarket())


class TestRunner:
    def test_two_schedulers_run_task_once(self, tmp_path):
        kernel = make_kernel(tmp_path)
        kernel.schedules.add("ежедневно 09:00", "report", report_payload("GOLD", [1]), now=NOW)
        first, second = ScheduleRunner(kernel), ScheduleRunner(kernel)
        due = kernel.schedules.due(NOW + timedelta(days=1))
        assert kernel.schedules.claim(due[0], NOW + timedelta(days=1))
        assert not kernel.schedules.claim(due[0], NOW + timedelta(days=1))
        later = NOW + timedelta(days=2)
        assert len(first.run_due(later)) == 1
        assert second.run_due(later) == []

    def test_report_task_delivered_with_chart(self, tmp_path):
        kernel = make_kernel(tmp_path)
        sent = []
        task = kernel.schedules.add("ежедневно 09:00", "report",
                                    report_payload("GOLD", [1, 7]), chat_id=42, now=NOW)
        runner = ScheduleRunner(kernel, notifier=lambda c, t, f: sent.append((c, t, f)))
        [result] = runner.run_due(NOW + timedelta(days=1))
        assert result.status == "ok" and result.report.exists()
        chat, text, files = sent[0]
        assert chat == 42 and "⏰ Отчёт GOLD" in text and "| 7 дн. |" in text
        assert files and files[0].suffix == ".png"
        assert kernel.schedules.get(task.id).last_status == "ok"
        assert kernel.forecasts.counts() == {"pending": 2}

    def test_agent_task_uses_fresh_session_and_saves_signed_report(self, tmp_path):
        kernel = make_kernel(tmp_path, ["Рынок спокоен"])
        task = kernel.schedules.add("ежедневно 09:00", "task", "Обзор рынка")
        result = ScheduleRunner(kernel).run(task)
        assert result.text == "Рынок спокоен"
        saved = result.report.read_text()
        assert "# Обзор рынка" in saved and SIGNATURE in saved
        assert kernel.orchestrator.director.history == []

    def test_verify_task(self, tmp_path):
        kernel = make_kernel(tmp_path)
        kernel.schedules.ensure_builtin()
        [task] = kernel.schedules.list()
        assert "Нет прогнозов" in ScheduleRunner(kernel).run(task).text

    def test_failure_isolated(self, tmp_path):
        kernel = make_kernel(tmp_path)
        bad = kernel.schedules.add("ежедневно 09:00", "report", report_payload("GOLD", [1]),
                                   now=NOW)
        good = kernel.schedules.add("ежедневно 09:00", "verify", "", now=NOW)
        kernel.market = StubMarket(fail=True)
        results = ScheduleRunner(kernel).run_due(NOW + timedelta(days=1))
        assert [r.status for r in results] == ["error", "ok"]
        assert "Нет связи" in kernel.schedules.get(bad.id).last_error
        assert kernel.schedules.get(good.id).last_status == "ok"


class TestToolAndCommands:
    def tool_call(self):
        return tool_use_response("schedule_task", {
            "schedule": "по будням 9:00", "kind": "report", "task": "",
            "symbol": "GOLD", "horizons": "1,7,15,30",
        })

    def test_tool_requires_approval(self, tmp_path):
        kernel = make_kernel(tmp_path, [self.tool_call(), "Не создано"])
        kernel.chat("присылай отчёт по золоту по будням")
        assert kernel.schedules.list() == []

    def test_tool_creates_task_for_chat(self, tmp_path):
        kernel = Kernel.create(
            llm=FakeLLMClient([self.tool_call(), "Готово"]), store=Store(),
            workspace_dir=tmp_path, self_check="off", approver=lambda n, p: True,
        )
        kernel.chat_id = 77
        kernel.chat("присылай отчёт по золоту по будням")
        [task] = kernel.schedules.list()
        assert task.chat_id == 77 and json.loads(task.payload)["horizons"] == [1, 7, 15, 30]

    def test_bad_tool_input_reported(self, tmp_path):
        kernel = make_kernel(tmp_path)
        tool = kernel.orchestrator.director.tools.get("schedule_task")
        with pytest.raises(ValueError):
            tool.handler(schedule="ежедневно 9:00", kind="report", task="", symbol="",
                         horizons="")

    def test_chat_commands(self, tmp_path):
        kernel = make_kernel(tmp_path)
        out = io.StringIO()
        app = ChatApp(kernel, Console(file=out, width=160, color_system=None), lambda _: "")
        app.handle('/schedule report "по будням 9:00" GOLD 1,7')
        app.handle('/schedule add «ежедневно 08:30» Сводка новостей')
        app.handle("/schedule")
        app.handle("/schedule pause 2")
        app.handle("/schedule run 1")
        app.handle("/schedule remove 2")
        app.handle("/schedule add ежедневно 9:00 без кавычек")
        text = out.getvalue()
        assert "Задача #1: Отчёт GOLD (1, 7 дн.) — по будням 09:00" in text
        assert "Сводка новостей" in text and "ежедневно 08:30" in text
        assert "на паузе" in text and "Задача #2 удалена" in text
        assert "| 7 дн. |" in text or "7 дн." in text
        assert "Формат: /schedule add" in text
        assert [t.id for t in kernel.schedules.list()] == [1]


def test_telegram_delivery(tmp_path):
    from tests.test_telegram import CHAT, OWNER, make_service

    service, io_, _ = make_service(tmp_path, [])
    service.handle_command(CHAT, OWNER, '/schedule report "ежедневно 09:00" GOLD 1')
    assert "Задача #1" in io_.texts()[-1]
    chart = tmp_path / "c.png"
    chart.write_bytes(b"png")
    service.notify(CHAT, "**Отчёт**", [chart, tmp_path / "missing.png"])
    assert io_.sent[-1] == (CHAT, "<b>Отчёт</b>", True)
    assert io_.photos == [(CHAT, "c.png", "c.png")]
    stop = service.start_scheduler(interval=60)
    stop.set()
    assert any(t.builtin for t in service._chat(CHAT).kernel.schedules.list())
