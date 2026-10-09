#!/usr/bin/env python3
# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Пример клиента HTTP API Prizolov Agent OS без сторонних библиотек.

    export PRIZOLOV_URL=http://127.0.0.1:8800
    export PRIZOLOV_KEY=<ключ из PRIZOLOV_API_KEYS>
    python examples/api_client.py "Спрогнозируй курс юаня ЦБ на неделю"
    python examples/api_client.py --report GOLD
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

URL = os.getenv("PRIZOLOV_URL", "http://127.0.0.1:8800").rstrip("/")
KEY = os.getenv("PRIZOLOV_KEY", "")


def call(method: str, path: str, body: dict = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(URL + path, data=data, method=method, headers={
        "Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as e:
        detail = json.loads(e.read() or b"{}").get("detail", e.reason)
        sys.exit(f"Ошибка {e.code}: {detail}")


def ask(message: str, session_id: str = None) -> dict:
    """Ставит задачу агентам и ждёт ответ, показывая ход работы."""
    job = call("POST", "/v1/tasks", {"message": message, "session_id": session_id})
    shown = 0
    while job["status"] not in ("done", "error"):
        time.sleep(1.5)
        job = call("GET", f"/v1/tasks/{job['id']}")
        for line in job["progress"][shown:]:
            print("  ", line)
        shown = len(job["progress"])
        if job["status"] == "waiting_approval":
            for approval in call("GET", "/v1/approvals"):
                if approval["job_id"] == job["id"]:
                    answer = input(f"{approval['description']}\nРазрешить? [y/N] ")
                    call("POST", f"/v1/approvals/{approval['id']}",
                         {"allow": answer.strip().lower() in ("y", "yes", "д", "да")})
    return job


def main() -> None:
    if not KEY:
        sys.exit("Задайте PRIZOLOV_KEY (ключ из PRIZOLOV_API_KEYS)")
    if len(sys.argv) == 3 and sys.argv[1] == "--report":
        report = call("POST", "/v1/reports", {"symbol": sys.argv[2], "horizons": [1, 7, 15, 30]})
        print(report["markdown"])
        return
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    job = ask(" ".join(sys.argv[1:]))
    if job["status"] == "error":
        sys.exit(job["error"])
    print("\n" + job["text"])
    print(f"\n[диалог {job['session_id']} · ${job['usage'].get('cost_usd', 0):.4f}]")


if __name__ == "__main__":
    main()
