# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""События системы: что делают агенты прямо сейчас.

На события подписываются интерфейсы (прогресс в CLI), журнал трассировки
и контроль бюджета. Ошибка подписчика не мешает работе агентов.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)

# Типы событий
LLM_REQUEST = "llm_request"          # агент обращается к модели (iteration)
LLM_RESPONSE = "llm_response"        # ответ модели (stop_reason, model, usage)
TOOL_CALL = "tool_call"              # вызов инструмента (tool, input, server)
TOOL_RESULT = "tool_result"          # результат инструмента (tool, is_error, output)
DELEGATION_START = "delegation_start"  # Директор поручил задачу (specialist, task)
DELEGATION_END = "delegation_end"    # специалист закончил (specialist, status)
SELF_CHECK = "self_check"            # самопроверка (score, issues)
REVISION = "revision"                # доработка ответа по замечаниям


@dataclass
class Event:
    type: str
    agent: str
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    )


Listener = Callable[[Event], None]


class EventBus:
    """Рассылает события подписчикам."""

    def __init__(self) -> None:
        self._listeners: List[Listener] = []
        self._lock = threading.Lock()

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """Подписывает и возвращает функцию отписки."""
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def emit(self, type: str, agent: str, **data: Any) -> Event:
        event = Event(type=type, agent=agent, data=data)
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception:  # noqa: BLE001 - подписчик не должен ломать агента
                logger.exception("Event listener failed on %s", type)
        return event
