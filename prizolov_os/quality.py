"""Метрики качества: отказы инструментов и источников, оценки критика и пользователя.

Монитор слушает события и копит статистику. Если инструмент или источник данных
стабильно сбоит, агент автоматически получает урок (например, сразу пробовать
другой источник).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from . import events as ev
from .events import Event, EventBus
from .memory import Store

SCHEMA = """
CREATE TABLE IF NOT EXISTS quality_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    agent TEXT NOT NULL,
    key TEXT NOT NULL,
    ok INTEGER NOT NULL,
    value REAL
);
CREATE INDEX IF NOT EXISTS idx_quality ON quality_events(kind, key, created_at);
"""

# Урок о сбоях появляется, если за неделю >= 10 вызовов и >= 30% из них - ошибки.
ALERT_WINDOW_DAYS = 7
ALERT_MIN_CALLS = 10
ALERT_ERROR_RATE = 0.3
LESSON_SOURCE = "quality"


@dataclass
class ToolQuality:
    key: str
    agent: str
    calls: int
    errors: int

    @property
    def error_rate(self) -> float:
        return self.errors / self.calls if self.calls else 0.0


class QualityMonitor:
    def __init__(self, store: Store, events: Optional[EventBus] = None) -> None:
        self.store = store
        store.add_schema(SCHEMA)
        if events is not None:
            events.subscribe(self.on_event)

    def on_event(self, event: Event) -> None:
        if event.type == ev.TOOL_RESULT:
            params = event.data.get("input") or {}
            key = event.data["tool"]
            if params.get("source"):
                key += f":{params['source']}"
            ok = not event.data.get("is_error")
            self.record("tool", event.agent, key, ok)
            if not ok:
                self._maybe_alert(event.agent, key)
        elif event.type == ev.SELF_CHECK:
            score = event.data["score"]
            self.record("critic", "director", "score", score >= 7, float(score))

    def record(
        self, kind: str, agent: str, key: str, ok: bool, value: Optional[float] = None
    ) -> None:
        self.store.execute(
            "INSERT INTO quality_events (created_at, kind, agent, key, ok, value) "
            "VALUES (?, ?, ?, ?, ?, ?)", (_now(), kind, agent, key, int(ok), value),
        )

    def record_feedback(self, agent: str, positive: bool) -> None:
        self.record("feedback", agent, "rating", positive)

    def tools(self, days: int = 30) -> List[ToolQuality]:
        rows = self.store.query(
            "SELECT key, agent, COUNT(*) AS calls, SUM(1 - ok) AS errors FROM quality_events "
            "WHERE kind = 'tool' AND created_at > ? GROUP BY key, agent ORDER BY errors DESC, "
            "calls DESC", (_since(days),),
        )
        return [ToolQuality(r["key"], r["agent"], r["calls"], r["errors"]) for r in rows]

    def report(self, days: int = 30) -> Dict[str, Any]:
        since = _since(days)
        critic = self.store.query(
            "SELECT COUNT(*) AS n, AVG(value) AS avg, SUM(1 - ok) AS low FROM quality_events "
            "WHERE kind = 'critic' AND created_at > ?", (since,),
        )[0]
        feedback = self.store.query(
            "SELECT agent, SUM(ok) AS good, SUM(1 - ok) AS bad FROM quality_events "
            "WHERE kind = 'feedback' AND created_at > ? GROUP BY agent", (since,),
        )
        return {
            "days": days,
            "tools": self.tools(days),
            "critic": {
                "checks": critic["n"],
                "average_score": round(critic["avg"], 1) if critic["avg"] is not None else None,
                "revisions": critic["low"] or 0,
            },
            "feedback": {r["agent"]: {"good": r["good"], "bad": r["bad"]} for r in feedback},
        }

    def _maybe_alert(self, agent: str, key: str) -> None:
        rows = self.store.query(
            "SELECT COUNT(*) AS calls, SUM(1 - ok) AS errors FROM quality_events "
            "WHERE kind = 'tool' AND key = ? AND created_at > ?",
            (key, _since(ALERT_WINDOW_DAYS)),
        )[0]
        calls, errors = rows["calls"], rows["errors"] or 0
        if calls < ALERT_MIN_CALLS or errors / calls < ALERT_ERROR_RATE:
            return
        tool, _, source = key.partition(":")
        marker = f"Инструмент {tool}" + (f" с источником {source}" if source else "")
        recent = [
            lesson for lesson in self.store.list_lessons(agent)
            if lesson.source == LESSON_SOURCE and lesson.text.startswith(marker)
            and lesson.created_at > _since(ALERT_WINDOW_DAYS)
        ]
        if recent:
            return
        self.store.add_lesson(
            agent,
            f"{marker} часто возвращает ошибки ({errors} из {calls} вызовов за неделю). "
            "При сбое сразу пробуй другой источник или способ и предупреждай пользователя, "
            "что данные могут быть неполными.",
            LESSON_SOURCE,
        )


def _since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="microseconds")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")
