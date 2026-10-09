# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""HTTP API на FastAPI: задачи агентам, отчёты, прогнозы, расписание, база знаний.

Запуск: prizolov api (pip install "prizolov-os[api]"). Все запросы к /v1 - с ключом
из PRIZOLOV_API_KEYS в заголовке Authorization: Bearer <ключ> или X-API-Key.
"""

import base64
import hashlib
import hmac
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Set

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from prizolov_os.__about__ import (
    HEADER,
    PROJECT_ID,
    USER_AGENT,
    __author__,
    __brand__,
    __email__,
    __license__,
    __title__,
    __url__,
    __version__,
)
from prizolov_os.core.kernel import Kernel

from .service import MAX_MESSAGE_CHARS, ApiError, ApiService

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8800

WEB_PAGE = Path(__file__).with_name("web") / "index.html"

_bearer = HTTPBearer(auto_error=False)
_api_key = APIKeyHeader(name="X-API-Key", auto_error=False)


# --- Тела запросов -----------------------------------------------------------


class TaskRequest(BaseModel):
    message: str = Field(..., max_length=MAX_MESSAGE_CHARS, description="Задача агентам")
    session_id: Optional[str] = Field(
        None, pattern=r"^[\w\-]{1,64}$",
        description="Продолжить диалог; без него создаётся новый",
    )


class ApprovalAnswer(BaseModel):
    allow: bool


class FeedbackRequest(BaseModel):
    positive: bool
    comment: str = Field("", max_length=2000)


class ReportRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32, examples=["GOLD", "GC=F", "SBER"])
    source: Optional[str] = Field(None, pattern="^(yahoo|moex|cbr)$")
    horizons: List[int] = Field(default_factory=lambda: [1, 7, 15, 30])
    history_days: int = 365


class CashflowRequest(BaseModel):
    path: str = Field(..., max_length=500, examples=["inbox/kl_to_1c.txt"])
    opening_balance: Optional[float] = Field(
        None, description="Остаток на начало; без него - из выписки 1С или 0"
    )
    days: int = Field(60, ge=1, le=365)


class PlannedPaymentRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    amount: float = Field(..., description="Платёж - минус, поступление - плюс")
    due_date: str = Field(..., examples=["2026-11-01", "01.11.2026"])
    repeat: str = Field("разово", examples=["ежемесячно"])
    until: Optional[str] = None


class PortfolioRequest(BaseModel):
    path: Optional[str] = Field(None, max_length=500, examples=["inbox/portfolio.csv"])
    use_tinvest: bool = False
    days: int = Field(30, ge=1, le=365)


class ScheduleRequest(BaseModel):
    schedule: str = Field(..., max_length=100, examples=["по будням 9:00", "0 9 * * 1-5"])
    kind: str = Field(..., pattern="^(task|report)$")
    task: str = Field("", max_length=MAX_MESSAGE_CHARS)
    symbol: str = Field("", max_length=32)
    horizons: List[int] = Field(default_factory=lambda: [1, 7, 15, 30])
    source: Optional[str] = Field(None, pattern="^(yahoo|moex|cbr)$")


# --- Приложение --------------------------------------------------------------


def create_app(
    service: ApiService, api_keys: Set[str], public_accuracy: bool = False
) -> FastAPI:
    """Собирает приложение. Без ключей доступа API не создаётся."""
    keys = {k for k in api_keys if k}
    if not keys:
        raise ValueError("Не заданы ключи доступа к API (PRIZOLOV_API_KEYS)")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        service.shutdown()

    app = FastAPI(
        lifespan=lifespan,
        title=f"{__title__} API",
        version=__version__,
        description=f"{HEADER}\n\nКоманда ИИ-агентов, прогнозы рынков и отчёты.",
        contact={"name": f"{__author__} / {__brand__}", "url": __url__, "email": __email__},
        license_info={"name": __license__, "identifier": __license__},
    )

    def authorize(
        bearer: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
        api_key: Optional[str] = Depends(_api_key),
    ) -> None:
        given = (bearer.credentials if bearer else None) or api_key or ""
        if not any(hmac.compare_digest(given.encode(), k.encode()) for k in keys):
            raise HTTPException(401, "Нужен ключ API", headers={"WWW-Authenticate": "Bearer"})

    @app.middleware("http")
    async def authorship(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers["X-Powered-By"] = USER_AGENT
        response.headers["X-Project-Id"] = PROJECT_ID
        return response

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.get("/health", tags=["service"])
    def health() -> Dict[str, Any]:
        return {"status": "ok", "product": __title__, "version": __version__,
                "author": __author__, "brand": __brand__, "project_id": PROJECT_ID}

    page, csp = _web_page()

    @app.get("/", include_in_schema=False)
    def web() -> HTMLResponse:
        """Веб-интерфейс: вход по ключу API, дальше все запросы - к /v1."""
        return HTMLResponse(page, headers={
            "Content-Security-Policy": csp,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        })

    v1 = [Depends(authorize)]

    # Задачи агентам

    @app.post("/v1/tasks", status_code=202, dependencies=v1, tags=["tasks"])
    def create_task(body: TaskRequest) -> Dict[str, Any]:
        """Ставит задачу Директору; результат - GET /v1/tasks/{id}."""
        return service.submit(body.message, body.session_id).as_dict()

    @app.get("/v1/tasks", dependencies=v1, tags=["tasks"])
    def list_tasks(limit: int = Query(20, ge=1, le=200)) -> List[Dict[str, Any]]:
        return [job.as_dict() for job in service.list_jobs(limit)]

    @app.get("/v1/tasks/{job_id}", dependencies=v1, tags=["tasks"])
    def get_task(job_id: str) -> Dict[str, Any]:
        return service.get_job(job_id).as_dict()

    @app.get("/v1/approvals", dependencies=v1, tags=["tasks"])
    def list_approvals() -> List[Dict[str, Any]]:
        """Действия, которые ждут подтверждения (например, запись файла)."""
        return [a.as_dict() for a in service.list_approvals()]

    @app.post("/v1/approvals/{approval_id}", dependencies=v1, tags=["tasks"])
    def answer_approval(approval_id: str, body: ApprovalAnswer) -> Dict[str, Any]:
        service.resolve_approval(approval_id, body.allow)
        return {"id": approval_id, "allowed": body.allow}

    # Диалоги

    @app.get("/v1/sessions", dependencies=v1, tags=["sessions"])
    def list_sessions(limit: int = Query(20, ge=1, le=200)) -> List[Dict[str, Any]]:
        return service.list_sessions(limit)

    @app.delete("/v1/sessions/{session_id}", status_code=204, dependencies=v1,
                tags=["sessions"])
    def delete_session(session_id: str) -> None:
        service.delete_session(session_id)

    @app.post("/v1/sessions/{session_id}/feedback", dependencies=v1, tags=["sessions"])
    def feedback(session_id: str, body: FeedbackRequest) -> Dict[str, Any]:
        """Оценка последнего ответа: из замечаний получаются уроки агентам."""
        return service.feedback(session_id, body.positive, body.comment)

    # Отчёты и файлы

    @app.post("/v1/reports", dependencies=v1, tags=["reports"])
    def create_report(body: ReportRequest) -> Dict[str, Any]:
        """Отчёт по активу без Claude: прогнозы на горизонты, таблица, график."""
        return service.report(body.symbol, body.source, body.horizons, body.history_days)

    @app.get("/v1/files/{path:path}", dependencies=v1, tags=["reports"])
    def download(path: str) -> FileResponse:
        """Скачать отчёт или график (папки reports/ и charts/)."""
        file = service.file_path(path)
        return FileResponse(file, filename=Path(file).name)

    @app.put("/v1/inbox/{filename}", dependencies=v1, tags=["knowledge"])
    async def upload(filename: str, request: Request) -> Dict[str, Any]:
        """Загрузить документ (тело запроса - файл); он попадёт в базу знаний."""
        data = await _read_limited(request)
        return service.upload(filename, data)

    @app.get("/v1/knowledge/search", dependencies=v1, tags=["knowledge"])
    def search(q: str = Query(..., min_length=2, max_length=500),
               limit: int = Query(6, ge=1, le=30)) -> List[Dict[str, Any]]:
        return service.search_knowledge(q, limit)

    # Деньги: выписки и платёжный календарь

    @app.get("/v1/statements", dependencies=v1, tags=["cashflow"])
    def statements() -> List[Dict[str, Any]]:
        """Файлы выписок в рабочей папке."""
        return service.statements()

    @app.post("/v1/cashflow", dependencies=v1, tags=["cashflow"])
    def cashflow(body: CashflowRequest) -> Dict[str, Any]:
        """Анализ выписки (1С, CSV, Excel), статьи расходов и платёжный календарь."""
        return service.cashflow(body.path, body.opening_balance, body.days)

    @app.get("/v1/calendar", dependencies=v1, tags=["cashflow"])
    def list_planned() -> List[Dict[str, Any]]:
        return service.list_planned()

    @app.post("/v1/calendar", status_code=201, dependencies=v1, tags=["cashflow"])
    def add_planned(body: PlannedPaymentRequest) -> Dict[str, Any]:
        """Плановый платёж (минус) или ожидаемое поступление (плюс)."""
        return service.add_planned(body.title, body.amount, body.due_date, body.repeat,
                                   body.until)

    @app.delete("/v1/calendar/{payment_id}", status_code=204, dependencies=v1,
                tags=["cashflow"])
    def remove_planned(payment_id: int) -> None:
        service.remove_planned(payment_id)

    # Прогнозы, качество, расходы

    @app.get("/v1/forecasts", dependencies=v1, tags=["forecasts"])
    def forecasts() -> Dict[str, Any]:
        """Соревнование методов: число прогнозов, процент попаданий, реальные сверки."""
        return service.forecasts()

    @app.post("/v1/portfolio", dependencies=v1, tags=["forecasts"])
    def portfolio(body: PortfolioRequest) -> Dict[str, Any]:
        """Портфель: стоимость, доли, риск, стресс-тесты, прогнозы по бумагам (без Claude)."""
        return service.portfolio(body.path, body.use_tinvest, body.days)

    @app.get("/v1/tenders", dependencies=v1, tags=["tenders"])
    def tenders(q: str = Query(..., min_length=3, max_length=200),
                max_price: float = Query(0, ge=0),
                only_new: bool = False) -> List[Dict[str, Any]]:
        """Открытые закупки 44-ФЗ / 223-ФЗ в ЕИС по запросу."""
        return service.tenders(q, max_price, only_new)

    @app.get("/v1/accuracy", dependencies=v1, tags=["forecasts"])
    def accuracy() -> Dict[str, Any]:
        """Сводка точности сверенных прогнозов: в целом, по классам, горизонтам, активам."""
        return service.accuracy()

    if public_accuracy:
        @app.get("/public/accuracy", include_in_schema=False)
        def public_accuracy_page() -> HTMLResponse:
            """Открытая страница точности (включается PRIZOLOV_PUBLIC_ACCURACY)."""
            return HTMLResponse(service.accuracy_page(), headers={
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
                                           "frame-ancestors 'none'",
                "Cache-Control": "public, max-age=300",
            })

        @app.get("/public/accuracy.json", include_in_schema=False)
        def public_accuracy_json() -> Dict[str, Any]:
            return service.accuracy()

    @app.post("/v1/forecasts/verify", dependencies=v1, tags=["forecasts"])
    def verify() -> Dict[str, Any]:
        return service.verify_forecasts()

    @app.get("/v1/quality", dependencies=v1, tags=["service"])
    def quality(days: int = Query(30, ge=1, le=365)) -> Dict[str, Any]:
        return service.quality(days)

    @app.get("/v1/budget", dependencies=v1, tags=["service"])
    def budget() -> Dict[str, Any]:
        return service.budget()

    @app.get("/v1/status", dependencies=v1, tags=["service"])
    def status() -> Dict[str, Any]:
        return service.status()

    # Расписание

    @app.get("/v1/schedules", dependencies=v1, tags=["schedules"])
    def list_schedules() -> List[Dict[str, Any]]:
        return service.list_schedules()

    @app.post("/v1/schedules", status_code=201, dependencies=v1, tags=["schedules"])
    def add_schedule(body: ScheduleRequest) -> Dict[str, Any]:
        return service.add_schedule(
            body.schedule, body.kind, body.task, body.symbol, body.horizons, body.source
        )

    @app.delete("/v1/schedules/{task_id}", status_code=204, dependencies=v1,
                tags=["schedules"])
    def remove_schedule(task_id: int) -> None:
        service.remove_schedule(task_id)

    @app.post("/v1/schedules/{task_id}/pause", dependencies=v1, tags=["schedules"])
    def pause(task_id: int) -> Dict[str, Any]:
        return service.set_schedule_enabled(task_id, False)

    @app.post("/v1/schedules/{task_id}/resume", dependencies=v1, tags=["schedules"])
    def resume(task_id: int) -> Dict[str, Any]:
        return service.set_schedule_enabled(task_id, True)

    @app.post("/v1/schedules/{task_id}/run", status_code=202, dependencies=v1,
              tags=["schedules"])
    def run_now(task_id: int) -> Dict[str, Any]:
        """Выполнить задачу сейчас; результат - GET /v1/tasks/{id}."""
        return service.run_schedule(task_id).as_dict()

    return app


def _web_page() -> "tuple[str, str]":
    """Страница и строгая политика CSP: разрешён только её собственный скрипт (по хэшу)."""
    page = WEB_PAGE.read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", page, flags=re.S)
    hashes = " ".join(
        "'sha256-" + base64.b64encode(hashlib.sha256(s.encode()).digest()).decode() + "'"
        for s in scripts
    )
    csp = (
        "default-src 'none'; "
        f"script-src {hashes}; "
        "style-src 'unsafe-inline'; "
        "img-src 'self' blob: data:; "
        "connect-src 'self'; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    )
    return page, csp


async def _read_limited(request: Request) -> bytes:
    from ..telegram.service import MAX_UPLOAD_BYTES

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise ApiError(413, "Файл больше 20 МБ")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise ApiError(413, "Файл больше 20 МБ")
        chunks.append(chunk)
    return b"".join(chunks)


def parse_api_keys(text: str) -> Set[str]:
    return {k.strip() for k in text.replace(";", ",").split(",") if k.strip()}


def run(host: Optional[str] = None, port: Optional[int] = None, scheduler: bool = False) -> int:
    """prizolov api: запускает сервер. Без ключей доступа не стартует."""
    try:
        import uvicorn
    except ImportError:
        print('Нужен FastAPI: pip install "prizolov-os[api]"')
        return 1
    from prizolov_os.config import settings

    keys = parse_api_keys(settings.api_keys)
    if not keys:
        print("Задайте ключи доступа в PRIZOLOV_API_KEYS (через запятую). Создать ключ:\n"
              'python -c "import secrets; print(secrets.token_urlsafe(32))"')
        return 1
    if any(len(k) < 16 for k in keys):
        print("Ключи в PRIZOLOV_API_KEYS должны быть не короче 16 символов")
        return 1
    service = ApiService(Kernel.create, Path(settings.workspace_dir), workers=settings.api_workers)
    if scheduler:
        from prizolov_os.scheduler import ScheduleRunner

        kernel = service.kernel
        kernel.schedules.ensure_builtin()
        ScheduleRunner(kernel).start_background()
    host = host or settings.api_host
    port = port or settings.api_port
    print(f"{HEADER}\nВеб-интерфейс: http://{host}:{port}  ·  API: http://{host}:{port}/docs")
    app = create_app(service, keys, public_accuracy=settings.public_accuracy)
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


__all__ = ["create_app", "parse_api_keys", "run"]
