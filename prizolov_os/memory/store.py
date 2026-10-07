"""Постоянная память Prizolov OS на SQLite.

Хранит диалоги, факты о пользователе, уроки агентов, версии системных
промптов и инструменты, предложенные агентами.
"""

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .search import rank

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    messages TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT NOT NULL,
    text TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prompt_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT NOT NULL,
    prompt TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS custom_tools (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    input_schema TEXT NOT NULL,
    code TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

# Статусы версий промптов: proposed -> active -> archived (или rejected).
PROPOSED, ACTIVE, ARCHIVED, REJECTED = "proposed", "active", "archived", "rejected"
# Статусы инструментов: pending -> approved (или rejected).
PENDING, APPROVED = "pending", "approved"


@dataclass
class Fact:
    id: int
    text: str
    created_at: str


@dataclass
class Lesson:
    id: int
    agent: str
    text: str
    source: str
    created_at: str


@dataclass
class PromptVersion:
    id: int
    agent: str
    prompt: str
    status: str
    note: str
    created_at: str


@dataclass
class CustomToolRecord:
    name: str
    description: str
    input_schema: Dict[str, Any]
    code: str
    status: str
    created_at: str


@dataclass
class SessionInfo:
    id: str
    title: str
    messages: int
    updated_at: str


class Store:
    """Хранилище. path=':memory:' - временная база в памяти (для тестов)."""

    def __init__(self, path: Union[str, Path] = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock, self._conn:
            return self._conn.execute(sql, params)

    def _query(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # --- Диалоги -------------------------------------------------------------

    def save_session(
        self, session_id: str, messages: List[Dict[str, Any]], title: str = ""
    ) -> None:
        now = _now()
        self._execute(
            "INSERT INTO sessions (id, title, messages, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "messages = excluded.messages, updated_at = excluded.updated_at, "
            "title = CASE WHEN sessions.title = '' THEN excluded.title ELSE sessions.title END",
            (session_id, title, json.dumps(messages, ensure_ascii=False), now, now),
        )

    def load_session(self, session_id: str) -> Optional[List[Dict[str, Any]]]:
        rows = self._query("SELECT messages FROM sessions WHERE id = ?", (session_id,))
        return json.loads(rows[0]["messages"]) if rows else None

    def list_sessions(self, limit: int = 20) -> List[SessionInfo]:
        rows = self._query(
            "SELECT id, title, messages, updated_at FROM sessions "
            "ORDER BY updated_at DESC LIMIT ?", (limit,)
        )
        return [
            SessionInfo(r["id"], r["title"], len(json.loads(r["messages"])), r["updated_at"])
            for r in rows
        ]

    def delete_session(self, session_id: str) -> bool:
        return self._execute("DELETE FROM sessions WHERE id = ?", (session_id,)).rowcount > 0

    # --- Факты ---------------------------------------------------------------

    def add_fact(self, text: str) -> int:
        text = text.strip()
        if not text:
            raise ValueError("Факт не может быть пустым")
        existing = self._query("SELECT id FROM facts WHERE text = ?", (text,))
        if existing:
            return existing[0]["id"]
        return self._execute(
            "INSERT INTO facts (text, created_at) VALUES (?, ?)", (text, _now())
        ).lastrowid

    def list_facts(self) -> List[Fact]:
        return [Fact(**dict(r)) for r in self._query("SELECT * FROM facts ORDER BY id")]

    def search_facts(self, query: str, limit: int = 10) -> List[Fact]:
        facts = self.list_facts()
        return rank(query, ((f, f.text) for f in facts), limit)

    def delete_fact(self, fact_id: int) -> bool:
        return self._execute("DELETE FROM facts WHERE id = ?", (fact_id,)).rowcount > 0

    # --- Уроки ---------------------------------------------------------------

    def add_lesson(self, agent: str, text: str, source: str) -> int:
        text = text.strip()
        if not text:
            raise ValueError("Урок не может быть пустым")
        return self._execute(
            "INSERT INTO lessons (agent, text, source, created_at) VALUES (?, ?, ?, ?)",
            (agent, text, source, _now()),
        ).lastrowid

    def list_lessons(self, agent: Optional[str] = None) -> List[Lesson]:
        if agent is None:
            rows = self._query("SELECT * FROM lessons ORDER BY id")
        else:
            rows = self._query("SELECT * FROM lessons WHERE agent = ? ORDER BY id", (agent,))
        return [Lesson(**dict(r)) for r in rows]

    def relevant_lessons(self, agent: str, query: str, limit: int = 5) -> List[Lesson]:
        lessons = self.list_lessons(agent)
        return rank(query, ((lesson, lesson.text) for lesson in lessons), limit)

    def delete_lesson(self, lesson_id: int) -> bool:
        return self._execute("DELETE FROM lessons WHERE id = ?", (lesson_id,)).rowcount > 0

    def lessons_since_last_prompt(self, agent: str) -> int:
        """Сколько уроков накоплено после последней принятой версии промпта."""
        rows = self._query(
            "SELECT MAX(created_at) AS t FROM prompt_versions "
            "WHERE agent = ? AND status IN (?, ?)", (agent, ACTIVE, ARCHIVED)
        )
        since = rows[0]["t"] or ""
        return self._query(
            "SELECT COUNT(*) AS n FROM lessons WHERE agent = ? AND created_at > ?",
            (agent, since),
        )[0]["n"]

    # --- Версии промптов -----------------------------------------------------

    def propose_prompt(self, agent: str, prompt: str, note: str = "") -> int:
        return self._execute(
            "INSERT INTO prompt_versions (agent, prompt, status, note, created_at) "
            "VALUES (?, ?, ?, ?, ?)", (agent, prompt, PROPOSED, note, _now())
        ).lastrowid

    def get_prompt_version(self, version_id: int) -> Optional[PromptVersion]:
        rows = self._query("SELECT * FROM prompt_versions WHERE id = ?", (version_id,))
        return PromptVersion(**dict(rows[0])) if rows else None

    def list_prompt_versions(self, agent: Optional[str] = None) -> List[PromptVersion]:
        if agent is None:
            rows = self._query("SELECT * FROM prompt_versions ORDER BY id")
        else:
            rows = self._query(
                "SELECT * FROM prompt_versions WHERE agent = ? ORDER BY id", (agent,)
            )
        return [PromptVersion(**dict(r)) for r in rows]

    def active_prompt(self, agent: str) -> Optional[PromptVersion]:
        rows = self._query(
            "SELECT * FROM prompt_versions WHERE agent = ? AND status = ? "
            "ORDER BY id DESC LIMIT 1", (agent, ACTIVE)
        )
        return PromptVersion(**dict(rows[0])) if rows else None

    def activate_prompt(self, version_id: int) -> PromptVersion:
        version = self.get_prompt_version(version_id)
        if version is None:
            raise ValueError(f"Нет версии промпта #{version_id}")
        if version.status not in (PROPOSED, ARCHIVED):
            raise ValueError(f"Версию #{version_id} нельзя активировать (статус {version.status})")
        self._execute(
            "UPDATE prompt_versions SET status = ? WHERE agent = ? AND status = ?",
            (ARCHIVED, version.agent, ACTIVE),
        )
        self._execute(
            "UPDATE prompt_versions SET status = ?, created_at = ? WHERE id = ?",
            (ACTIVE, _now(), version_id),
        )
        return self.get_prompt_version(version_id)  # type: ignore[return-value]

    def reject_prompt(self, version_id: int) -> None:
        self._execute(
            "UPDATE prompt_versions SET status = ? WHERE id = ? AND status = ?",
            (REJECTED, version_id, PROPOSED),
        )

    def rollback_prompt(self, agent: str) -> Optional[PromptVersion]:
        """Отключает активную версию и возвращает предыдущую (None - исходный промпт)."""
        active = self.active_prompt(agent)
        if active is None:
            raise ValueError(f"У агента {agent} нет изменённого промпта")
        self._execute("UPDATE prompt_versions SET status = ? WHERE id = ?", (REJECTED, active.id))
        rows = self._query(
            "SELECT id FROM prompt_versions WHERE agent = ? AND status = ? "
            "ORDER BY id DESC LIMIT 1", (agent, ARCHIVED)
        )
        return self.activate_prompt(rows[0]["id"]) if rows else None

    # --- Инструменты, созданные агентами -------------------------------------

    def add_custom_tool(
        self, name: str, description: str, input_schema: Dict[str, Any], code: str
    ) -> None:
        existing = self.get_custom_tool(name)
        if existing and existing.status == APPROVED:
            raise ValueError(f"Инструмент '{name}' уже подключён")
        self._execute(
            "INSERT OR REPLACE INTO custom_tools "
            "(name, description, input_schema, code, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, description, json.dumps(input_schema, ensure_ascii=False), code,
             PENDING, _now()),
        )

    def get_custom_tool(self, name: str) -> Optional[CustomToolRecord]:
        rows = self._query("SELECT * FROM custom_tools WHERE name = ?", (name,))
        return _tool_record(rows[0]) if rows else None

    def list_custom_tools(self, status: Optional[str] = None) -> List[CustomToolRecord]:
        if status is None:
            rows = self._query("SELECT * FROM custom_tools ORDER BY created_at")
        else:
            rows = self._query(
                "SELECT * FROM custom_tools WHERE status = ? ORDER BY created_at", (status,)
            )
        return [_tool_record(r) for r in rows]

    def set_custom_tool_status(self, name: str, status: str) -> None:
        if self._execute(
            "UPDATE custom_tools SET status = ? WHERE name = ?", (status, name)
        ).rowcount == 0:
            raise ValueError(f"Нет инструмента '{name}'")


def _tool_record(row: sqlite3.Row) -> CustomToolRecord:
    data = dict(row)
    data["input_schema"] = json.loads(data["input_schema"])
    return CustomToolRecord(**data)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")
