# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Логика HTTP API, независимая от веб-фреймворка.

Задачи агентам выполняются в фоне: клиент получает номер задачи и опрашивает её
состояние. Подтверждения опасных действий ждут ответа через API.
"""

import json
import logging
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from prizolov_os import events as ev
from prizolov_os.core.kernel import Kernel
from prizolov_os.events import Event
from prizolov_os.llm import LLMError
from prizolov_os.scheduler import ScheduledTask, ScheduleRunner, describe, report_payload

from ..render import format_params, short
from ..telegram.format import progress_line
from ..telegram.service import INBOX, MAX_UPLOAD_BYTES, UPLOAD_SUFFIXES, _safe_name, _unique

logger = logging.getLogger(__name__)

APPROVAL_TIMEOUT = 300.0
MAX_MESSAGE_CHARS = 20_000
MAX_JOBS = 200
MAX_SESSIONS = 32
MAX_HORIZON_DAYS = 365
# Файлы рабочей папки, которые можно скачать через API.
DOWNLOAD_DIRS = ("reports", "charts")
ACTIVE = ("queued", "running", "waiting_approval")

KernelFactory = Callable[..., Kernel]


class ApiError(Exception):
    """Ошибка запроса: status - HTTP-код ответа."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Approval:
    id: str
    job_id: str
    tool: str
    description: str
    created: float = field(default_factory=time.time)
    event: threading.Event = field(default_factory=threading.Event, repr=False)
    allowed: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "job_id": self.job_id, "tool": self.tool,
                "description": self.description, "created": self.created}


@dataclass
class Job:
    """Фоновая задача: поручение агентам или запуск задачи из расписания."""

    id: str
    kind: str
    session_id: Optional[str]
    request: str
    status: str = "queued"  # queued, running, waiting_approval, done, error
    created: float = field(default_factory=time.time)
    finished: Optional[float] = None
    text: str = ""
    stop_reason: str = ""
    error: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)
    progress: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class _Session:
    kernel: Kernel
    busy: threading.Lock = field(default_factory=threading.Lock)


class ApiService:
    def __init__(
        self,
        kernel_factory: KernelFactory,
        workspace_dir: Path,
        workers: int = 2,
        approval_timeout: float = APPROVAL_TIMEOUT,
        max_sessions: int = MAX_SESSIONS,
    ) -> None:
        self.kernel_factory = kernel_factory
        self.workspace_dir = Path(workspace_dir)
        self.approval_timeout = approval_timeout
        self.max_sessions = max_sessions
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="api-job")
        self._sessions: "OrderedDict[str, _Session]" = OrderedDict()
        self._jobs: "OrderedDict[str, Job]" = OrderedDict()
        self._approvals: Dict[str, Approval] = {}
        self._lock = threading.RLock()
        self._kernel: Optional[Kernel] = None

    @property
    def kernel(self) -> Kernel:
        """Общее ядро для отчётов, прогнозов, расписания и статистики."""
        with self._lock:
            if self._kernel is None:
                self._kernel = self.kernel_factory(workspace_dir=self.workspace_dir)
            return self._kernel

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # --- Задачи агентам ------------------------------------------------------

    def submit(self, message: str, session_id: Optional[str] = None) -> Job:
        message = message.strip()
        if not message:
            raise ApiError(422, "Пустая задача")
        if len(message) > MAX_MESSAGE_CHARS:
            raise ApiError(413, f"Задача длиннее {MAX_MESSAGE_CHARS} символов")
        session_id = session_id or f"api-{uuid.uuid4().hex[:12]}"
        session = self._session(session_id)
        if not session.busy.acquire(blocking=False):
            raise ApiError(409, f"Диалог {session_id} ещё выполняет предыдущую задачу")
        job = self._new_job("chat", session_id, message)
        try:
            self._executor.submit(self._run_chat, job, session)
        except RuntimeError:
            session.busy.release()
            raise ApiError(503, "Сервер останавливается") from None
        return job

    def _run_chat(self, job: Job, session: _Session) -> None:
        job.status = "running"
        unsubscribe = session.kernel.events.subscribe(lambda e: self._on_event(job, e))
        try:
            result = session.kernel.chat(job.request)
        except LLMError as e:
            self._fail(job, str(e))
        except Exception as e:  # noqa: BLE001 - клиент должен узнать о сбое
            logger.exception("API job %s failed", job.id)
            self._fail(job, f"Ошибка: {e}")
        else:
            job.text = result.text
            job.stop_reason = result.stop_reason
            job.usage = {
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "cost_usd": round(result.usage.cost_usd, 6),
                "iterations": result.iterations,
            }
            job.status = "done"
            job.finished = time.time()
        finally:
            unsubscribe()
            session.busy.release()

    def _on_event(self, job: Job, event: Event) -> None:
        if event.type == ev.TOOL_RESULT and event.data.get("tool", "").startswith("chart_"):
            job.files.extend(_charts_from(event.data.get("output", "")))
        line = progress_line(event)
        if line:
            job.progress.append(line)

    def _fail(self, job: Job, error: str) -> None:
        job.error = error
        job.status = "error"
        job.finished = time.time()

    def get_job(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ApiError(404, f"Задача {job_id} не найдена")
        return job

    def list_jobs(self, limit: int = 20) -> List[Job]:
        with self._lock:
            return list(reversed(self._jobs.values()))[:limit]

    def _new_job(self, kind: str, session_id: Optional[str], request: str) -> Job:
        job = Job(uuid.uuid4().hex[:16], kind, session_id, request)
        with self._lock:
            self._jobs[job.id] = job
            while len(self._jobs) > MAX_JOBS:
                oldest = next(iter(self._jobs.values()))
                if oldest.status not in ("done", "error"):
                    break
                self._jobs.popitem(last=False)
        return job

    # --- Подтверждения -------------------------------------------------------

    def approver_for(self, session_id: str) -> Callable[[str, Dict[str, Any]], bool]:
        def approve(tool: str, params: Dict[str, Any]) -> bool:
            job = self._running_job(session_id)
            if tool == "write_file":
                text = (f"Записать файл {params.get('path')}: "
                        f"{short(str(params.get('content', '')), 300)}")
            else:
                text = f"Выполнить {tool}({format_params(params)})"
            approval = Approval(uuid.uuid4().hex[:12], job.id if job else "", tool, text)
            with self._lock:
                self._approvals[approval.id] = approval
            if job is not None:
                job.status = "waiting_approval"
                job.progress.append(f"Ждёт подтверждения {approval.id}: {text}")
            answered = approval.event.wait(self.approval_timeout)
            with self._lock:
                self._approvals.pop(approval.id, None)
            if job is not None:
                job.status = "running"
                if not answered:
                    job.progress.append(f"Нет ответа на {approval.id} - действие отклонено")
            return answered and approval.allowed

        return approve

    def list_approvals(self) -> List[Approval]:
        with self._lock:
            return sorted(self._approvals.values(), key=lambda a: a.created)

    def resolve_approval(self, approval_id: str, allow: bool) -> None:
        with self._lock:
            approval = self._approvals.get(approval_id)
        if approval is None:
            raise ApiError(404, "Запрос подтверждения не найден или уже неактуален")
        approval.allowed = allow
        approval.event.set()

    def _running_job(self, session_id: str) -> Optional[Job]:
        with self._lock:
            for job in reversed(self._jobs.values()):
                if job.session_id == session_id and job.status in ACTIVE:
                    return job
        return None

    # --- Диалоги -------------------------------------------------------------

    def _session(self, session_id: str) -> _Session:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                self._sessions.move_to_end(session_id)
                return session
            kernel = self.kernel_factory(
                approver=self.approver_for(session_id), session_id=session_id,
                workspace_dir=self.workspace_dir,
            )
            if kernel.store.load_session(session_id) is not None:
                kernel.resume(session_id)
            session = self._sessions[session_id] = _Session(kernel)
            self._evict()
            return session

    def _evict(self) -> None:
        """Выгружает из памяти давно не используемые диалоги (они остаются в базе)."""
        for sid in list(self._sessions):
            if len(self._sessions) <= self.max_sessions:
                return
            if not self._sessions[sid].busy.locked():
                del self._sessions[sid]

    def list_sessions(self, limit: int = 20) -> List[Dict[str, Any]]:
        return [asdict(s) for s in self.kernel.store.list_sessions(limit)]

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None and session.busy.locked():
                raise ApiError(409, "Диалог выполняет задачу")
            self._sessions.pop(session_id, None)
        if not self.kernel.store.delete_session(session_id):
            raise ApiError(404, f"Диалог {session_id} не найден")

    def feedback(self, session_id: str, positive: bool, comment: str = "") -> Dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise ApiError(404, "Оценивать можно последний ответ диалога, открытого в API")
        try:
            lesson = session.kernel.feedback(positive, comment)
        except ValueError as e:
            raise ApiError(409, str(e)) from None
        return {"lesson": lesson.text if lesson else None}

    # --- Отчёты и файлы ------------------------------------------------------

    def report(
        self, symbol: str, source: Optional[str], horizons: Sequence[int], history_days: int
    ) -> Dict[str, Any]:
        from prizolov_os.forecasting import ForecastEngine, ForecastJournal
        from prizolov_os.market import MarketDataError
        from prizolov_os.reports import market_report, save_report, to_markdown

        horizons = _check_horizons(horizons)
        if not 30 <= history_days <= 3650:
            raise ApiError(422, "history_days: от 30 до 3650")
        kernel = self.kernel
        try:
            report = market_report(
                kernel.market, ForecastEngine(ForecastJournal(kernel.store)), symbol, source,
                horizons, history_days,
            )
        except MarketDataError as e:
            raise ApiError(502, f"Не удалось получить котировки: {e}") from None
        except ValueError as e:
            raise ApiError(422, str(e)) from None
        path = save_report(report, self.workspace_dir / "reports")
        return {
            "source": report.source,
            "symbol": report.symbol,
            "currency": report.currency,
            "unit": report.unit,
            "created": report.created.isoformat(timespec="seconds"),
            "last_price": report.last_price,
            "summary": report.summary,
            "forecasts": [
                {"horizon_days": row.horizon_days, **row.forecast} for row in report.rows
            ],
            "markdown": to_markdown(report),
            "report_file": self._relative(path),
            "chart_file": self._relative(report.chart) if report.chart else None,
        }

    def file_path(self, relative: str) -> Path:
        """Путь к файлу для скачивания: только reports/ и charts/ рабочей папки."""
        root = self.workspace_dir.resolve()
        path = (root / relative).resolve()
        allowed = [root / d for d in DOWNLOAD_DIRS]
        if not any(path.is_relative_to(d) for d in allowed) or not path.is_file():
            raise ApiError(404, "Файл не найден")
        return path

    def upload(self, filename: str, data: bytes) -> Dict[str, Any]:
        name = _safe_name(filename)
        if Path(name).suffix.lower() not in UPLOAD_SUFFIXES:
            raise ApiError(415, "Поддерживаются PDF, Word (.docx), Excel (.xlsx), CSV, TXT и MD")
        if len(data) > MAX_UPLOAD_BYTES:
            raise ApiError(413, "Файл больше 20 МБ")
        target = _unique(self.workspace_dir / INBOX / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        indexed = None
        if self.kernel.knowledge is not None:
            indexed = asdict(self.kernel.knowledge.index())
        return {"path": self._relative(target), "index": indexed}

    def search_knowledge(self, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        knowledge = self.kernel.knowledge
        if knowledge is None:
            return []
        return [{**asdict(hit), "source": hit.source} for hit in knowledge.search(query, limit)]

    def _relative(self, path: Path) -> str:
        return Path(path).resolve().relative_to(self.workspace_dir.resolve()).as_posix()

    # --- Деньги: выписки и платёжный календарь -------------------------------

    @property
    def calendar(self) -> Any:
        from prizolov_os.payment_calendar import PaymentCalendar

        return PaymentCalendar(self.kernel.store)

    def statements(self) -> List[Dict[str, Any]]:
        """Файлы выписок в рабочей папке (CSV, Excel, .txt из клиент-банка)."""
        root = self.workspace_dir.resolve()
        files = []
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() not in (".csv", ".xlsx", ".xlsm", ".txt") or not path.is_file():
                continue
            relative = path.relative_to(root)
            if relative.parts and relative.parts[0] in ("reports", "charts"):
                continue
            files.append({"path": relative.as_posix(), "size": path.stat().st_size})
        return files[:200]

    def cashflow(self, path: str, opening_balance: Optional[float], days: int) -> Dict[str, Any]:
        """Анализ выписки, статьи и платёжный календарь (без Claude)."""
        from prizolov_os import charts
        from prizolov_os.analytics import analyze_cashflow
        from prizolov_os.analytics.categories import by_category
        from prizolov_os.analytics.statements import load_statement
        from prizolov_os.payment_calendar import project
        from prizolov_os.tools.builtin import Workspace

        if not 1 <= days <= 365:
            raise ApiError(422, "days: от 1 до 365")
        try:
            file = Workspace(self.workspace_dir).resolve(path)
            statement = load_statement(file)
        except FileNotFoundError:
            raise ApiError(404, f"Файл {path} не найден") from None
        except (PermissionError, ValueError) as e:
            raise ApiError(422, str(e)) from None
        opening = opening_balance if opening_balance is not None else (
            statement.opening_balance or 0.0
        )
        transactions = statement.transactions
        analysis = analyze_cashflow(transactions, opening, days)
        planned = self.calendar.list()
        plan = project(transactions, opening, planned, days) if planned else None
        out = self.workspace_dir / "reports"
        out.mkdir(parents=True, exist_ok=True)
        stem = "".join(c if c.isalnum() else "_" for c in Path(path).stem)
        chart = charts.cashflow_forecast_chart(
            out / f"cashflow-{stem}.png", transactions, opening, analysis["forecast"]
        )
        return {
            "source_format": statement.source_format,
            "opening_balance": opening,
            "opening_from_file": opening_balance is None and statement.opening_balance is not None,
            "analysis": analysis,
            "categories": by_category(transactions),
            "calendar": plan,
            "chart_file": self._relative(chart),
        }

    def list_planned(self) -> List[Dict[str, Any]]:
        return [p.as_dict() for p in self.calendar.list()]

    def add_planned(
        self, title: str, amount: float, due_date: str, repeat: str, until: Optional[str]
    ) -> Dict[str, Any]:
        from prizolov_os.analytics.cashflow import parse_date
        from prizolov_os.payment_calendar import parse_repeat

        try:
            payment = self.calendar.add(
                title, amount, parse_date(due_date), parse_repeat(repeat),
                parse_date(until) if until else None,
            )
        except ValueError as e:
            raise ApiError(422, str(e)) from None
        return payment.as_dict()

    def remove_planned(self, payment_id: int) -> None:
        if not self.calendar.remove(payment_id):
            raise ApiError(404, f"Нет планового платежа #{payment_id}")

    # --- Прогнозы, качество, расходы -----------------------------------------

    def forecasts(self) -> Dict[str, Any]:
        from prizolov_os.forecasting.classify import ASSET_CLASSES
        from prizolov_os.forecasting.methods import METHOD_NAMES

        journal = self.kernel.forecasts
        board = journal.leaderboard()
        for row in board:
            row["backtest"] = row["backtest"].as_dict()
            row["live"] = row["live"].as_dict()
            row["asset_class_name"] = ASSET_CLASSES.get(row["asset_class"], row["asset_class"])
            row["method_name"] = METHOD_NAMES.get(row["method"], row["method"])
        return {"counts": journal.counts(), "methods": board}

    def portfolio(self, path: Optional[str], use_tinvest: bool, days: int) -> Dict[str, Any]:
        from prizolov_os.config import settings
        from prizolov_os.portfolio import (
            PortfolioError,
            TInvestClient,
            analyze_portfolio,
            load_portfolio,
        )
        from prizolov_os.tools.builtin import Workspace

        if not 1 <= days <= 365:
            raise ApiError(422, "days: от 1 до 365")
        try:
            if use_tinvest:
                positions = TInvestClient(settings.tinvest_token or "").positions()
            elif path:
                positions = load_portfolio(Workspace(self.workspace_dir).resolve(path))
            else:
                raise ApiError(422, "Укажите path или use_tinvest")
            return analyze_portfolio(positions, self.kernel.market, None, days)
        except FileNotFoundError:
            raise ApiError(404, f"Файл {path} не найден") from None
        except (PermissionError, PortfolioError, ValueError) as e:
            raise ApiError(422, str(e)) from None

    def tenders(self, query: str, max_price: float, only_new: bool) -> List[Dict[str, Any]]:
        from prizolov_os.tenders import TenderSearch, TenderSearchError

        try:
            found = TenderSearch(self.kernel.store).search(query, max_price=max_price,
                                                           only_new=only_new)
        except ValueError as e:
            raise ApiError(422, str(e)) from None
        except TenderSearchError as e:
            raise ApiError(502, str(e)) from None
        return [t.as_dict() for t in found]

    def accuracy(self) -> Dict[str, Any]:
        from prizolov_os.accuracy import accuracy_data

        return accuracy_data(self.kernel.store)

    def accuracy_page(self) -> str:
        from prizolov_os.accuracy import render_html

        return render_html(self.accuracy())

    def verify_forecasts(self) -> Dict[str, Any]:
        report = self.kernel.verify_forecasts()
        return {
            "verified": [
                {"id": f.id, "symbol": f.symbol, "source": f.source,
                 "target_date": f.target_date.isoformat(), "median": f.median,
                 "actual": f.actual, "error_pct": f.error_pct, "hit_80": f.hit_80,
                 "direction_ok": f.direction_ok}
                for f in report.verified
            ],
            "unverifiable": report.unverifiable,
            "errors": report.errors,
        }

    def quality(self, days: int = 30) -> Dict[str, Any]:
        report = self.kernel.quality.report(days)
        report["tools"] = [
            {**asdict(t), "error_rate": round(t.error_rate, 3)} for t in report["tools"]
        ]
        return report

    def budget(self) -> Dict[str, Any]:
        budget = self.kernel.budget
        if budget is None:
            return {}
        return {
            "task_limit_usd": budget.task_limit_usd,
            "day_limit_usd": budget.day_limit_usd,
            "today_spent_usd": round(budget.today_spent_usd(), 6),
            "total_spent_usd": round(budget.total_spent_usd(), 6),
            "history": budget.history(30),
        }

    def status(self) -> Dict[str, Any]:
        status = self.kernel.get_status()
        with self._lock:
            status["api"] = {
                "open_sessions": len(self._sessions),
                "jobs": sum(1 for j in self._jobs.values() if j.status not in ("done", "error")),
                "pending_approvals": len(self._approvals),
            }
        return status

    # --- Расписание ----------------------------------------------------------

    def list_schedules(self) -> List[Dict[str, Any]]:
        return [_schedule_dict(t) for t in self.kernel.schedules.list()]

    def add_schedule(
        self, schedule: str, kind: str, task: str = "", symbol: str = "",
        horizons: Sequence[int] = (1, 7, 15, 30), source: Optional[str] = None,
    ) -> Dict[str, Any]:
        if kind == "report":
            if not symbol.strip():
                raise ApiError(422, "Для отчёта нужен symbol")
            payload = report_payload(symbol, _check_horizons(horizons), source)
        elif kind == "task":
            payload = task
        else:
            raise ApiError(422, "kind: task или report")
        try:
            created = self.kernel.schedules.add(schedule, kind, payload)
        except ValueError as e:
            raise ApiError(422, str(e)) from None
        return _schedule_dict(created)

    def remove_schedule(self, task_id: int) -> None:
        self._schedule(task_id)
        try:
            self.kernel.schedules.remove(task_id)
        except ValueError as e:
            raise ApiError(409, str(e)) from None

    def set_schedule_enabled(self, task_id: int, enabled: bool) -> Dict[str, Any]:
        self._schedule(task_id)
        self.kernel.schedules.set_enabled(task_id, enabled)
        return _schedule_dict(self._schedule(task_id))

    def run_schedule(self, task_id: int) -> Job:
        """Запускает задачу из расписания сейчас (в фоне)."""
        task = self._schedule(task_id)
        job = self._new_job("schedule", None, f"#{task.id} {task.title}")

        def run() -> None:
            job.status = "running"
            try:
                result = ScheduleRunner(self.kernel).run(task)
            except Exception as e:  # noqa: BLE001
                logger.exception("Scheduled task #%s failed via API", task_id)
                return self._fail(job, f"Ошибка: {e}")
            job.text = result.text
            job.stop_reason = result.status
            files = [result.report] if result.report else []
            job.files = [self._relative(p) for p in [*files, *result.files]]
            if result.status == "error":
                return self._fail(job, result.text)
            job.status = "done"
            job.finished = time.time()

        self._executor.submit(run)
        return job

    def _schedule(self, task_id: int) -> ScheduledTask:
        task = self.kernel.schedules.get(task_id)
        if task is None:
            raise ApiError(404, f"Задача расписания #{task_id} не найдена")
        return task


def _check_horizons(horizons: Sequence[int]) -> List[int]:
    values = sorted(set(int(h) for h in horizons))
    if not values or not all(1 <= h <= MAX_HORIZON_DAYS for h in values):
        raise ApiError(422, f"Горизонты: от 1 до {MAX_HORIZON_DAYS} дней")
    return values


def _schedule_dict(task: ScheduledTask) -> Dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "kind": task.kind,
        "schedule": task.schedule,
        "cron": task.cron,
        "description": describe(task.cron),
        "enabled": task.enabled,
        "builtin": task.builtin,
        "next_run": task.next_run.isoformat(),
        "last_run": task.last_run,
        "last_status": task.last_status,
        "last_error": task.last_error,
    }


def _charts_from(output: str) -> List[str]:
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return []
    charts = data.get("charts") or ([data["chart"]] if data.get("chart") else [])
    return [str(c) for c in charts]


__all__ = ["ApiError", "ApiService", "Approval", "Job"]
