# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Журнал трассировки: каждый шаг агентов в файле logs/trace-ГГГГ-ММ-ДД.jsonl.

По журналу можно восстановить, почему система ответила именно так: какие агенты
работали, какие инструменты вызывали, сколько это стоило. Тексты задач и
результатов по умолчанию сокращаются: в них могут быть данные пользователя.
"""

import json
import threading
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Union

from .__about__ import PROJECT_ID, __version__
from .events import Event, EventBus

PREVIEW_CHARS = 200


class Tracer:
    def __init__(
        self,
        directory: Union[str, Path],
        include_content: bool = False,
        session: Optional[Callable[[], str]] = None,
    ) -> None:
        self.directory = Path(directory)
        self.include_content = include_content
        self._session = session or (lambda: "")
        self._lock = threading.Lock()

    def attach(self, events: EventBus) -> Callable[[], None]:
        return events.subscribe(self.on_event)

    @property
    def path(self) -> Path:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.directory / f"trace-{day}.jsonl"

    def on_event(self, event: Event) -> None:
        self.write({
            "ts": event.timestamp,
            "session": self._session(),
            "type": event.type,
            "agent": event.agent,
            "data": self._clean(event.data),
        })

    def write(self, record: dict) -> None:
        record.setdefault("version", __version__)
        record.setdefault("project", PROJECT_ID)
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as file:
                file.write(line + "\n")

    def _clean(self, value: Any) -> Any:
        if is_dataclass(value) and not isinstance(value, type):
            return self._clean(asdict(value))
        if isinstance(value, dict):
            return {k: self._clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._clean(v) for v in value]
        if isinstance(value, str) and not self.include_content and len(value) > PREVIEW_CHARS:
            return value[:PREVIEW_CHARS] + f"… [+{len(value) - PREVIEW_CHARS} симв.]"
        return value
