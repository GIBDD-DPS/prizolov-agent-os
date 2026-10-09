# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Расписание задач: регулярные поручения агентам, отчёты и сверка прогнозов.

Расписание задаётся по-человечески («ежедневно 09:00», «по будням 9:30»,
«по понедельникам 10:00», «каждые 6 часов») или строкой cron. Внутри всё хранится
как cron. Время - в часовом поясе PRIZOLOV_TIMEZONE.
"""

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set
from zoneinfo import ZoneInfo

from .__about__ import SIGNATURE
from .memory import Store

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule TEXT NOT NULL,
    cron TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    chat_id INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1,
    builtin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    next_run TEXT NOT NULL,
    last_run TEXT,
    last_status TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT ''
);
"""

KINDS = ("task", "report", "verify")
MIN_INTERVAL_MINUTES = 15
WEEKDAYS = {
    "понедельник": 1, "вторник": 2, "сред": 3, "четверг": 4, "пятниц": 5, "суббот": 6,
    "воскресен": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 0,
}


class ScheduleError(ValueError):
    """Расписание не удалось разобрать."""


# --- Разбор расписания -------------------------------------------------------


def to_cron(text: str) -> str:
    """Переводит расписание в cron (минута час день месяц день_недели)."""
    raw = " ".join(text.strip().lower().split())
    if len(raw.split()) == 5 and re.fullmatch(r"[\d*/,\- ]+", raw):
        CronSpec(raw)  # проверка
        return raw
    time_match = re.search(r"(\d{1,2})[:.](\d{2})", raw)
    minute = hour = None
    if time_match:
        hour, minute = int(time_match.group(1)), int(time_match.group(2))
        if hour > 23 or minute > 59:
            raise ScheduleError(f"Некорректное время: {time_match.group(0)}")

    every = re.search(r"(?:кажды[ейх]|every)\s*(\d+)?\s*(час|часа|часов|h|hour|hours|"
                      r"минут|минуты|min|minutes)", raw)
    if every or re.search(r"(каждый|every)\s+(час|hour)", raw):
        count = int(every.group(1)) if every and every.group(1) else 1
        unit = every.group(2) if every else "час"
        if unit.startswith(("мин", "min")):
            if count < MIN_INTERVAL_MINUTES or 60 % count:
                raise ScheduleError(
                    f"Интервал в минутах: от {MIN_INTERVAL_MINUTES}, делитель 60 (15, 20, 30)"
                )
            return f"*/{count} * * * *"
        if not 1 <= count <= 23 or 24 % count:
            raise ScheduleError("Интервал в часах: делитель 24 (1, 2, 3, 4, 6, 8, 12)")
        return f"{minute or 0} */{count} * * *" if count > 1 else f"{minute or 0} * * * *"

    if hour is None:
        raise ScheduleError("Укажите время, например: ежедневно 09:00")
    if re.search(r"будн|weekday", raw):
        return f"{minute} {hour} * * 1-5"
    if re.search(r"выходн|weekend", raw):
        return f"{minute} {hour} * * 0,6"
    days = sorted({num for name, num in WEEKDAYS.items() if name in raw})
    if days:
        return f"{minute} {hour} * * {','.join(map(str, days))}"
    if re.search(r"ежедневн|каждый день|daily|every day", raw):
        return f"{minute} {hour} * * *"
    raise ScheduleError(
        "Не понял расписание. Примеры: «ежедневно 09:00», «по будням 9:30», "
        "«по понедельникам 10:00», «каждые 6 часов» или cron «0 9 * * 1-5»"
    )


class CronSpec:
    """Минимальная реализация cron: *, числа, списки, диапазоны и шаги."""

    RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]

    def __init__(self, expression: str) -> None:
        parts = expression.split()
        if len(parts) != 5:
            raise ScheduleError("В cron должно быть 5 полей: минута час день месяц день_недели")
        self.fields: List[Set[int]] = [
            _cron_field(part, low, high) for part, (low, high) in zip(parts, self.RANGES)
        ]
        self.any_day = parts[2] == "*"
        self.any_weekday = parts[4] == "*"

    def matches(self, moment: datetime) -> bool:
        minute, hour, day, month, weekday = self.fields
        if moment.minute not in minute or moment.hour not in hour or moment.month not in month:
            return False
        day_ok = moment.day in day
        weekday_ok = (moment.isoweekday() % 7) in weekday
        if self.any_day or self.any_weekday:
            return day_ok and weekday_ok
        return day_ok or weekday_ok  # как в классическом cron

    def next_after(self, moment: datetime) -> datetime:
        candidate = moment.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(366 * 24 * 60):
            if self.matches(candidate):
                return candidate
            candidate += timedelta(minutes=1)
        raise ScheduleError("Расписание не срабатывает ни разу за год")


def _cron_field(part: str, low: int, high: int) -> Set[int]:
    values: Set[int] = set()
    for item in part.split(","):
        step = 1
        if "/" in item:
            item, step_text = item.split("/", 1)
            step = int(step_text)
            if step <= 0:
                raise ScheduleError("Шаг в cron должен быть положительным")
        if item == "*":
            start, end = low, high
        elif "-" in item:
            start, end = (int(x) for x in item.split("-", 1))
        else:
            start = end = int(item)
        if not (low <= start <= high and low <= end <= high and start <= end):
            raise ScheduleError(f"Значение вне диапазона {low}-{high}: {part}")
        values.update(range(start, end + 1, step))
    return values


def next_run(cron: str, after: datetime, tz: str) -> datetime:
    """Следующий запуск (UTC) после момента after (UTC) по расписанию в поясе tz."""
    zone = ZoneInfo(tz)
    local = after.astimezone(zone)
    return CronSpec(cron).next_after(local).astimezone(timezone.utc)


def describe(cron: str) -> str:
    minute, hour, day, month, weekday = cron.split()
    if minute.startswith("*/"):
        return f"каждые {minute[2:]} мин."
    if hour == "*":
        return f"каждый час в :{int(minute):02d}"
    if hour.startswith("*/"):
        return f"каждые {hour[2:]} ч. в :{int(minute):02d}"
    clock = f"{int(hour):02d}:{int(minute):02d}" if hour.isdigit() and minute.isdigit() else ""
    if day == "*" and month == "*":
        names = {"*": "ежедневно", "1-5": "по будням", "0,6": "по выходным"}
        if weekday in names:
            return f"{names[weekday]} {clock}".strip()
        labels = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"]
        if re.fullmatch(r"[0-6](,[0-6])*", weekday):
            return f"{', '.join(labels[int(d)] for d in weekday.split(','))} {clock}".strip()
    return f"cron {cron}"


# --- Хранилище задач ---------------------------------------------------------


@dataclass
class ScheduledTask:
    id: int
    schedule: str
    cron: str
    kind: str
    payload: str
    chat_id: Optional[int]
    enabled: bool
    builtin: bool
    next_run: datetime
    last_run: Optional[str]
    last_status: str
    last_error: str

    @property
    def title(self) -> str:
        if self.kind == "report":
            data = json.loads(self.payload)
            return f"Отчёт {data['symbol']} ({', '.join(map(str, data['horizons']))} дн.)"
        if self.kind == "verify":
            return "Сверка прогнозов с фактом"
        return self.payload


class ScheduleStore:
    def __init__(self, store: Store, tz: str = "Europe/Moscow") -> None:
        self.store = store
        self.tz = tz
        ZoneInfo(tz)  # проверка пояса
        store.add_schema(SCHEMA)

    def add(
        self, schedule: str, kind: str, payload: str, chat_id: Optional[int] = None,
        builtin: bool = False, now: Optional[datetime] = None,
    ) -> ScheduledTask:
        if kind not in KINDS:
            raise ScheduleError(f"Тип задачи: {', '.join(KINDS)}")
        if kind == "task" and not payload.strip():
            raise ScheduleError("Опишите, что делать")
        cron = to_cron(schedule)
        now = now or datetime.now(timezone.utc)
        first = next_run(cron, now, self.tz)
        task_id = self.store.execute(
            "INSERT INTO scheduled_tasks (schedule, cron, kind, payload, chat_id, builtin, "
            "created_at, next_run) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (schedule.strip(), cron, kind, payload.strip(), chat_id, int(builtin),
             now.isoformat(), first.isoformat()),
        ).lastrowid
        return self.get(task_id)  # type: ignore[return-value]

    def get(self, task_id: int) -> Optional[ScheduledTask]:
        rows = self.store.query("SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,))
        return _task(rows[0]) if rows else None

    def list(
        self, chat_id: Optional[int] = None, include_builtin: bool = True
    ) -> List[ScheduledTask]:
        rows = self.store.query("SELECT * FROM scheduled_tasks ORDER BY id")
        tasks = [_task(r) for r in rows]
        if chat_id is not None:
            tasks = [t for t in tasks if t.chat_id == chat_id or t.builtin]
        if not include_builtin:
            tasks = [t for t in tasks if not t.builtin]
        return tasks

    def remove(self, task_id: int) -> bool:
        task = self.get(task_id)
        if task is None:
            return False
        if task.builtin:
            raise ScheduleError("Встроенную задачу нельзя удалить, её можно приостановить")
        cursor = self.store.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        return cursor.rowcount > 0

    def set_enabled(self, task_id: int, enabled: bool) -> None:
        if self.store.execute(
            "UPDATE scheduled_tasks SET enabled = ? WHERE id = ?", (int(enabled), task_id)
        ).rowcount == 0:
            raise ScheduleError(f"Нет задачи #{task_id}")

    def due(self, now: datetime) -> List[ScheduledTask]:
        rows = self.store.query(
            "SELECT * FROM scheduled_tasks WHERE enabled = 1 AND next_run <= ? ORDER BY next_run",
            (now.isoformat(),),
        )
        return [_task(r) for r in rows]

    def mark_run(self, task: ScheduledTask, status: str, error: str, now: datetime) -> None:
        # Пропущенные запуски не наверстываем: следующий - от текущего момента.
        following = next_run(task.cron, now, self.tz)
        self.store.execute(
            "UPDATE scheduled_tasks SET last_run = ?, last_status = ?, last_error = ?, "
            "next_run = ? WHERE id = ?",
            (now.isoformat(), status, error[:500], following.isoformat(), task.id),
        )

    def ensure_builtin(self) -> None:
        """Ежедневная сверка прогнозов - чтобы система училась, даже если чат не открывают."""
        if not any(t.kind == "verify" and t.builtin for t in self.list()):
            self.add("ежедневно 08:50", "verify", "", builtin=True)


def _task(row: Any) -> ScheduledTask:
    return ScheduledTask(
        id=row["id"], schedule=row["schedule"], cron=row["cron"], kind=row["kind"],
        payload=row["payload"], chat_id=row["chat_id"], enabled=bool(row["enabled"]),
        builtin=bool(row["builtin"]), next_run=datetime.fromisoformat(row["next_run"]),
        last_run=row["last_run"], last_status=row["last_status"], last_error=row["last_error"],
    )


# --- Выполнение --------------------------------------------------------------

# notifier(chat_id, text, files) - отправить результат в Telegram.
Notifier = Callable[[int, str, Sequence[Path]], None]


@dataclass
class RunResult:
    task: ScheduledTask
    status: str
    text: str
    report: Optional[Path] = None
    files: List[Path] = field(default_factory=list)


class ScheduleRunner:
    """Выполняет задачи по расписанию от имени ядра (новый диалог на каждый запуск)."""

    def __init__(self, kernel: Any, notifier: Optional[Notifier] = None) -> None:
        self.kernel = kernel
        self.schedules: ScheduleStore = kernel.schedules
        self.notifier = notifier
        self.reports_dir = Path(kernel.workspace_dir) / "reports"
        self._lock = threading.Lock()

    def run_due(self, now: Optional[datetime] = None) -> List[RunResult]:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            return [self.run(task, now) for task in self.schedules.due(now)]

    def run(self, task: ScheduledTask, now: Optional[datetime] = None) -> RunResult:
        now = now or datetime.now(timezone.utc)
        logger.info("Scheduled task #%s (%s) started", task.id, task.kind)
        try:
            result = self._execute(task)
        except Exception as e:  # noqa: BLE001 - сбой одной задачи не должен останавливать остальные
            logger.exception("Scheduled task #%s failed", task.id)
            result = RunResult(task, "error", f"Задача #{task.id} не выполнена: {e}")
        self.schedules.mark_run(task, result.status, result.text if result.status == "error"
                                else "", now)
        self._deliver(result)
        return result

    def _execute(self, task: ScheduledTask) -> RunResult:
        if task.kind == "verify":
            report = self.kernel.verify_forecasts()
            hits = sum(1 for f in report.verified if f.hit_80)
            text = (f"Сверено прогнозов: {len(report.verified)}, в 80%-й интервал попало {hits}."
                    if report.verified else "Нет прогнозов, срок которых наступил.")
            if report.errors:
                text += " Не удалось получить факт: " + "; ".join(report.errors)
            return RunResult(task, "ok", text)
        if task.kind == "report":
            return self._report(task)
        worker = self.kernel.spawn()
        answer = worker.run(task.payload)
        status = "ok" if answer.completed else answer.stop_reason
        path = self._save(task, f"# {task.title}\n\n{answer.text}")
        return RunResult(task, status, answer.text, path, self._charts(worker))

    def _report(self, task: ScheduledTask) -> RunResult:
        from .forecasting import ForecastEngine, ForecastJournal
        from .reports import market_report, save_report, to_markdown

        data = json.loads(task.payload)
        report = market_report(
            self.kernel.market, ForecastEngine(ForecastJournal(self.kernel.store)),
            data["symbol"], data.get("source"), data["horizons"],
        )
        path = save_report(report, self.reports_dir)
        return RunResult(task, "ok", to_markdown(report), path,
                         [report.chart] if report.chart else [])

    def _save(self, task: ScheduledTask, text: str) -> Path:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.reports_dir / f"task{task.id}-{stamp}.md"
        if SIGNATURE not in text:
            text = text.rstrip() + f"\n\n---\n_{SIGNATURE}_\n"
        path.write_text(text, encoding="utf-8")
        return path

    def _charts(self, worker: Any) -> List[Path]:
        charts_dir = Path(self.kernel.workspace_dir) / "charts"
        started = getattr(worker, "created_at", None)
        if not charts_dir.is_dir() or started is None:
            return []
        return sorted(p for p in charts_dir.glob("*.png") if p.stat().st_mtime >= started)

    def _deliver(self, result: RunResult) -> None:
        task = result.task
        if self.notifier is None or task.chat_id is None:
            return
        header = f"⏰ {task.title} ({describe(task.cron)})"
        text = f"{header}\n\n{result.text}"
        if result.report is not None:
            text += f"\n\nОтчёт: {result.report.relative_to(self.kernel.workspace_dir)}"
        try:
            self.notifier(task.chat_id, text, result.files)
        except Exception:  # noqa: BLE001
            logger.exception("Scheduled task #%s: delivery failed", task.id)

    def run_forever(self, stop: threading.Event, interval: float = 30.0) -> None:
        """Цикл планировщика: раз в interval секунд запускает наступившие задачи."""
        while not stop.is_set():
            try:
                self.run_due()
            except Exception:  # noqa: BLE001
                logger.exception("Scheduler loop error")
            stop.wait(interval)

    def start_background(self, interval: float = 30.0) -> threading.Event:
        stop = threading.Event()
        threading.Thread(
            target=self.run_forever, args=(stop, interval), name="prizolov-scheduler",
            daemon=True,
        ).start()
        return stop


def report_payload(symbol: str, horizons: Sequence[int], source: Optional[str] = None) -> str:
    data: Dict[str, Any] = {"symbol": symbol.upper(), "horizons": sorted(set(horizons))}
    if source:
        data["source"] = source
    return json.dumps(data, ensure_ascii=False)
