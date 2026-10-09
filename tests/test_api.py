# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Тесты HTTP API (FastAPI TestClient, без сети: модель и котировки имитируются)."""

import json
import time

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from cli.api.server import create_app, parse_api_keys  # noqa: E402
from cli.api.service import ApiService  # noqa: E402
from prizolov_os.__about__ import PROJECT_ID, __author__  # noqa: E402
from prizolov_os.core.kernel import Kernel  # noqa: E402
from prizolov_os.llm import FakeLLMClient, tool_use_response  # noqa: E402
from prizolov_os.memory import Store  # noqa: E402
from tests.test_reports import StubMarket  # noqa: E402

KEY = "test-key-0123456789abcdef"
AUTH = {"Authorization": f"Bearer {KEY}"}


def make_client(tmp_path, responses=(), market=None, **kwargs):
    store = Store()
    llm = FakeLLMClient(list(responses))
    market = market or StubMarket()

    def factory(**kw):
        return Kernel.create(llm=llm, store=store, self_check="off", market=market, **kw)

    service = ApiService(factory, tmp_path, **kwargs)
    return TestClient(create_app(service, {KEY})), service, llm


def wait_job(client, job_id, statuses=("done", "error"), timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/v1/tasks/{job_id}", headers=AUTH).json()
        if job["status"] in statuses:
            return job
        time.sleep(0.02)
    raise AssertionError(f"Задача {job_id} не завершилась: {job}")


class TestAccess:
    def test_no_keys_no_app(self, tmp_path):
        service = ApiService(lambda **kw: None, tmp_path)
        with pytest.raises(ValueError):
            create_app(service, set())

    def test_requests_without_key_rejected(self, tmp_path):
        client, _, llm = make_client(tmp_path, ["секрет"])
        assert client.post("/v1/tasks", json={"message": "привет"}).status_code == 401
        bad = {"Authorization": "Bearer wrong"}
        assert client.get("/v1/status", headers=bad).status_code == 401
        assert client.get("/v1/files/reports/x.md").status_code == 401
        assert llm.calls == []

    def test_x_api_key_header(self, tmp_path):
        client, _, _ = make_client(tmp_path)
        assert client.get("/v1/schedules", headers={"X-API-Key": KEY}).status_code == 200

    def test_health_is_open_and_signed(self, tmp_path):
        client, _, _ = make_client(tmp_path)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["author"] == __author__
        assert response.headers["X-Project-Id"] == PROJECT_ID
        assert "Prizolov-Agent-OS" in response.headers["X-Powered-By"]
        schema = client.get("/openapi.json").json()
        assert __author__ in schema["info"]["contact"]["name"]

    def test_parse_api_keys(self):
        assert parse_api_keys(" a, b;c ,") == {"a", "b", "c"}
        assert parse_api_keys("") == set()


class TestTasks:
    def test_task_runs_in_background(self, tmp_path):
        client, _, _ = make_client(tmp_path, [
            tool_use_response("delegate", {"agent": "assistant", "task": "Посчитай 2+2"}),
            "4", "Ответ: 4",
        ])
        response = client.post("/v1/tasks", json={"message": "Сколько будет 2+2?"},
                               headers=AUTH)
        assert response.status_code == 202
        job = wait_job(client, response.json()["id"])
        assert job["status"] == "done" and job["text"] == "Ответ: 4"
        assert job["session_id"].startswith("api-")
        assert any("Ассистент" in line for line in job["progress"])
        assert job["usage"]["iterations"] == 2
        sessions = client.get("/v1/sessions", headers=AUTH).json()
        assert sessions[0]["id"] == job["session_id"]

    def test_session_continues(self, tmp_path):
        client, _, llm = make_client(tmp_path, ["первый", "второй"])
        first = client.post("/v1/tasks", json={"message": "раз", "session_id": "s1"},
                            headers=AUTH).json()
        wait_job(client, first["id"])
        second = client.post("/v1/tasks", json={"message": "два", "session_id": "s1"},
                             headers=AUTH).json()
        assert wait_job(client, second["id"])["text"] == "второй"
        assert len(llm.calls[-1]["messages"]) == 3

    def test_validation(self, tmp_path):
        client, _, _ = make_client(tmp_path)
        assert client.post("/v1/tasks", json={"message": "  "}, headers=AUTH).status_code == 422
        bad_session = {"message": "x", "session_id": "../etc"}
        assert client.post("/v1/tasks", json=bad_session, headers=AUTH).status_code == 422
        assert client.get("/v1/tasks/nope", headers=AUTH).status_code == 404

    def test_approval_allow(self, tmp_path):
        client, _, _ = make_client(tmp_path, [
            tool_use_response("delegate", {"agent": "writer", "task": "сохрани"}),
            tool_use_response("write_file", {"path": "note.md", "content": "текст"}),
            "готово", "Итог",
        ])
        job = client.post("/v1/tasks", json={"message": "запиши"}, headers=AUTH).json()
        wait_job(client, job["id"], ("waiting_approval",))
        approvals = client.get("/v1/approvals", headers=AUTH).json()
        assert approvals[0]["tool"] == "write_file" and approvals[0]["job_id"] == job["id"]
        answer = client.post(f"/v1/approvals/{approvals[0]['id']}", json={"allow": True},
                             headers=AUTH)
        assert answer.status_code == 200
        assert wait_job(client, job["id"])["status"] == "done"
        assert (tmp_path / "note.md").exists()
        assert client.get("/v1/approvals", headers=AUTH).json() == []

    def test_approval_timeout_denies(self, tmp_path):
        client, _, _ = make_client(tmp_path, [
            tool_use_response("delegate", {"agent": "writer", "task": "сохрани"}),
            tool_use_response("write_file", {"path": "note.md", "content": "текст"}),
            "не вышло", "Итог",
        ], approval_timeout=0.05)
        job = client.post("/v1/tasks", json={"message": "запиши"}, headers=AUTH).json()
        done = wait_job(client, job["id"])
        assert done["status"] == "done"
        assert not (tmp_path / "note.md").exists()
        assert any("отклонено" in line for line in done["progress"])

    def test_unknown_approval(self, tmp_path):
        client, _, _ = make_client(tmp_path)
        response = client.post("/v1/approvals/abc", json={"allow": True}, headers=AUTH)
        assert response.status_code == 404

    def test_llm_error_reported(self, tmp_path):
        from prizolov_os.llm import LLMError

        client, _, llm = make_client(tmp_path)

        def broken(**kwargs):
            raise LLMError("Нет ключа")

        llm.complete = broken
        job = client.post("/v1/tasks", json={"message": "x"}, headers=AUTH).json()
        done = wait_job(client, job["id"])
        assert done["status"] == "error" and "Нет ключа" in done["error"]

    def test_feedback_creates_lesson(self, tmp_path):
        client, _, _ = make_client(tmp_path, [
            "ответ", json.dumps({"agent": "director", "lesson": "Указывай источник данных"}),
        ])
        job = client.post("/v1/tasks", json={"message": "x", "session_id": "fb"},
                          headers=AUTH).json()
        wait_job(client, job["id"])
        response = client.post("/v1/sessions/fb/feedback",
                               json={"positive": False, "comment": "Указывай источник"},
                               headers=AUTH)
        assert response.status_code == 200
        assert "источник" in response.json()["lesson"]
        missing = client.post("/v1/sessions/none/feedback", json={"positive": True},
                              headers=AUTH)
        assert missing.status_code == 404

    def test_delete_session(self, tmp_path):
        client, _, _ = make_client(tmp_path, ["ответ"])
        job = client.post("/v1/tasks", json={"message": "x", "session_id": "del"},
                          headers=AUTH).json()
        wait_job(client, job["id"])
        assert client.delete("/v1/sessions/del", headers=AUTH).status_code == 204
        assert client.delete("/v1/sessions/del", headers=AUTH).status_code == 404


class TestReports:
    def test_report_and_download(self, tmp_path):
        client, _, llm = make_client(tmp_path)
        response = client.post("/v1/reports", json={"symbol": "GOLD",
                                                    "horizons": [30, 1, 7, 15]}, headers=AUTH)
        assert response.status_code == 200
        data = response.json()
        assert data["source"] == "cbr"
        assert [f["horizon_days"] for f in data["forecasts"]] == [1, 7, 15, 30]
        assert "probability_up" in data["forecasts"][0]
        assert data["report_file"].startswith("reports/")
        md = client.get(f"/v1/files/{data['report_file']}", headers=AUTH)
        assert md.status_code == 200 and "GOLD" in md.text
        png = client.get(f"/v1/files/{data['chart_file']}", headers=AUTH)
        assert png.content[:4] == b"\x89PNG"
        assert llm.calls == []  # отчёт без Claude
        counts = client.get("/v1/forecasts", headers=AUTH).json()["counts"]
        assert counts.get("pending") == 4

    def test_report_errors(self, tmp_path):
        client, _, _ = make_client(tmp_path, market=StubMarket(fail=True))
        response = client.post("/v1/reports", json={"symbol": "GOLD"}, headers=AUTH)
        assert response.status_code == 502 and "Нет связи" in response.json()["detail"]
        bad = client.post("/v1/reports", json={"symbol": "GOLD", "horizons": [0]},
                          headers=AUTH)
        assert bad.status_code == 422

    def test_download_limited_to_reports_and_charts(self, tmp_path):
        client, _, _ = make_client(tmp_path)
        (tmp_path / "secret.txt").write_text("x")
        (tmp_path / "reports").mkdir()
        for path in ("secret.txt", "reports/../secret.txt", "reports/missing.md"):
            assert client.get(f"/v1/files/{path}", headers=AUTH).status_code == 404


class TestKnowledge:
    def test_upload_and_search(self, tmp_path):
        client, _, _ = make_client(tmp_path)
        text = "Договор поставки: срок оплаты 30 дней".encode()
        response = client.put("/v1/inbox/../dogovor.txt", content=text, headers=AUTH)
        assert response.status_code in (404, 405)  # обход пути не принимается
        response = client.put("/v1/inbox/dogovor.txt", content=text, headers=AUTH)
        assert response.status_code == 200
        assert response.json()["path"] == "inbox/dogovor.txt"
        hits = client.get("/v1/knowledge/search", params={"q": "срок оплаты"},
                          headers=AUTH).json()
        assert hits and hits[0]["path"] == "inbox/dogovor.txt"

    def test_upload_rejects_unknown_type(self, tmp_path):
        client, _, _ = make_client(tmp_path)
        response = client.put("/v1/inbox/run.exe", content=b"MZ", headers=AUTH)
        assert response.status_code == 415


class TestSchedules:
    def test_report_schedule_lifecycle(self, tmp_path):
        client, _, _ = make_client(tmp_path)
        created = client.post("/v1/schedules", json={
            "schedule": "по будням 9:00", "kind": "report", "symbol": "gold",
            "horizons": [7, 1],
        }, headers=AUTH)
        assert created.status_code == 201
        task = created.json()
        assert task["cron"] == "0 9 * * 1-5" and "GOLD" in task["title"]
        paused = client.post(f"/v1/schedules/{task['id']}/pause", headers=AUTH).json()
        assert paused["enabled"] is False
        job = client.post(f"/v1/schedules/{task['id']}/run", headers=AUTH)
        assert job.status_code == 202
        done = wait_job(client, job.json()["id"])
        assert done["status"] == "done" and done["files"][0].startswith("reports/")
        assert client.delete(f"/v1/schedules/{task['id']}", headers=AUTH).status_code == 204
        assert client.post(f"/v1/schedules/{task['id']}/run", headers=AUTH).status_code == 404

    def test_schedule_validation(self, tmp_path):
        client, _, _ = make_client(tmp_path)
        bad = client.post("/v1/schedules", json={"schedule": "когда-нибудь", "kind": "task",
                                                 "task": "обзор"}, headers=AUTH)
        assert bad.status_code == 422
        no_symbol = client.post("/v1/schedules", json={"schedule": "ежедневно 9:00",
                                                       "kind": "report"}, headers=AUTH)
        assert no_symbol.status_code == 422

    def test_builtin_cannot_be_removed(self, tmp_path):
        client, service, _ = make_client(tmp_path)
        service.kernel.schedules.ensure_builtin()
        builtin = client.get("/v1/schedules", headers=AUTH).json()[0]
        assert builtin["builtin"] is True
        assert client.delete(f"/v1/schedules/{builtin['id']}", headers=AUTH).status_code == 409


class TestService:
    def test_status_quality_budget(self, tmp_path):
        client, _, _ = make_client(tmp_path)
        status = client.get("/v1/status", headers=AUTH).json()
        assert "api" in status and status["api"]["jobs"] == 0
        assert "tools" in client.get("/v1/quality", headers=AUTH).json()
        assert client.get("/v1/budget", headers=AUTH).json()["task_limit_usd"] >= 0

    def test_verify_forecasts(self, tmp_path):
        client, _, _ = make_client(tmp_path)
        result = client.post("/v1/forecasts/verify", headers=AUTH).json()
        assert result == {"verified": [], "unverifiable": 0, "errors": []}

    def test_cli_refuses_without_keys(self, monkeypatch, capsys):
        from cli.api import server
        from prizolov_os.config import settings

        monkeypatch.setattr(settings, "api_keys", "")
        assert server.run() == 1
        monkeypatch.setattr(settings, "api_keys", "short")
        assert server.run() == 1
        assert "16" in capsys.readouterr().out


class TestWeb:
    def test_page_served_with_strict_csp(self, tmp_path):
        client, _, _ = make_client(tmp_path)
        response = client.get("/")
        assert response.status_code == 200
        assert "Prizolov Agent OS" in response.text and "Dm.Andreyanov" in response.text
        csp = response.headers["Content-Security-Policy"]
        assert "script-src 'sha256-" in csp and "unsafe-inline" not in csp.split(";")[1]
        assert "frame-ancestors 'none'" in csp
        assert response.headers["X-Project-Id"] == PROJECT_ID

    def test_forecast_names_are_readable(self, tmp_path):
        client, _, _ = make_client(tmp_path)
        client.post("/v1/reports", json={"symbol": "GOLD", "horizons": [7]}, headers=AUTH)
        methods = client.get("/v1/forecasts", headers=AUTH).json()["methods"]
        assert methods and methods[0]["asset_class_name"] == "драгметаллы"
        assert all(m["method_name"] != m["method"] for m in methods)


class TestCashflow:
    def test_statement_calendar_and_gap(self, tmp_path):
        from pathlib import Path

        client, _, llm = make_client(tmp_path)
        demo = Path(__file__).resolve().parent.parent / "examples" / "demo_bank_statement_1c.txt"
        upload = client.put("/v1/inbox/kl_to_1c.txt", content=demo.read_bytes(), headers=AUTH)
        assert upload.status_code == 200
        files = client.get("/v1/statements", headers=AUTH).json()
        assert {"path": "inbox/kl_to_1c.txt", "size": demo.stat().st_size} in files
        added = client.post("/v1/calendar", json={
            "title": "Заработная плата", "amount": -900000, "due_date": "05.10.2026",
            "repeat": "ежемесячно"}, headers=AUTH)
        assert added.status_code == 201 and added.json()["category"] == "Зарплата"
        bad = client.post("/v1/calendar", json={"title": "X", "amount": 0,
                                                "due_date": "2026-10-01"}, headers=AUTH)
        assert bad.status_code == 422
        result = client.post("/v1/cashflow", json={"path": "inbox/kl_to_1c.txt", "days": 60},
                             headers=AUTH).json()
        assert result["source_format"] == "1c" and result["opening_from_file"] is True
        assert result["calendar"]["gap"]["date"] == "2026-10-05"
        assert any(c["category"] == "Налоги и взносы" for c in result["categories"])
        png = client.get(f"/v1/files/{result['chart_file']}", headers=AUTH)
        assert png.content[:4] == b"\x89PNG"
        payment_id = added.json()["id"]
        assert client.delete(f"/v1/calendar/{payment_id}", headers=AUTH).status_code == 204
        assert client.delete(f"/v1/calendar/{payment_id}", headers=AUTH).status_code == 404
        assert llm.calls == []

    def test_cashflow_errors(self, tmp_path):
        client, _, _ = make_client(tmp_path)
        missing = client.post("/v1/cashflow", json={"path": "inbox/none.csv"}, headers=AUTH)
        assert missing.status_code == 404
        outside = client.post("/v1/cashflow", json={"path": "../etc/passwd"}, headers=AUTH)
        assert outside.status_code == 422
