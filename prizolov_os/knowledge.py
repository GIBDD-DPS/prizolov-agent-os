# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""База знаний (RAG): поиск по документам рабочей папки.

Документы режутся на фрагменты (по абзацам, ~1000 символов) и индексируются
полнотекстовым поиском SQLite FTS5 с ранжированием BM25. Всё хранится локально,
наружу ничего не уходит. Формы русских слов учитываются поиском по началу слова
(«золота» найдёт «золото»). Индекс обновляется только по изменённым файлам и
перед каждым поиском, так что он всегда актуален.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from .documents import DocumentError, extract_text, is_document
from .memory import Store

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_files (
    path TEXT PRIMARY KEY,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    chunks INTEGER NOT NULL,
    error TEXT NOT NULL DEFAULT ''
);
CREATE VIRTUAL TABLE IF NOT EXISTS kb_chunks USING fts5(
    path UNINDEXED,
    location UNINDEXED,
    body,
    tokenize = 'unicode61 remove_diacritics 2',
    prefix = '2 3 4 5'
);
"""

TEXT_SUFFIXES = {".txt", ".md", ".csv"}
SKIP_DIRS = {"charts"}
CHUNK_CHARS = 1000
OVERLAP_CHARS = 150
STEM_CHARS = 5
MAX_RESULT_CHARS = 1200
_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass
class Hit:
    path: str
    location: str
    text: str
    score: float

    @property
    def source(self) -> str:
        return f"{self.path}, {self.location}" if self.location else self.path


@dataclass
class IndexReport:
    added: List[str] = field(default_factory=list)
    updated: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    errors: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.removed)


class KnowledgeBase:
    def __init__(self, store: Store, root: Path) -> None:
        self.store = store
        self.root = Path(root).resolve()
        store.add_schema(SCHEMA)

    # --- Индекс ----------------------------------------------------------------

    def index(self, force: bool = False) -> IndexReport:
        """Индексирует новые и изменённые файлы, убирает удалённые."""
        report = IndexReport()
        known = {
            r["path"]: (r["mtime"], r["size"])
            for r in self.store.query("SELECT path, mtime, size FROM kb_files")
        }
        seen = set()
        for file in self._files():
            rel = file.relative_to(self.root).as_posix()
            seen.add(rel)
            stat = file.stat()
            if not force and known.get(rel) == (stat.st_mtime, stat.st_size):
                continue
            self._index_file(file, rel, stat.st_mtime, stat.st_size, report)
            (report.updated if rel in known else report.added).append(rel)
        for rel in set(known) - seen:
            self._remove(rel)
            report.removed.append(rel)
        return report

    def _files(self) -> List[Path]:
        if not self.root.is_dir():
            return []
        files = []
        for file in sorted(self.root.rglob("*")):
            parts = file.relative_to(self.root).parts
            hidden = parts[-1].startswith(".")
            if hidden or any(p.startswith(".") or p in SKIP_DIRS for p in parts[:-1]):
                continue
            if file.is_file() and (file.suffix.lower() in TEXT_SUFFIXES or is_document(file)):
                if not _is_bank_export(file):
                    files.append(file)
        return files

    def _index_file(
        self, file: Path, rel: str, mtime: float, size: int, report: IndexReport
    ) -> None:
        self._remove(rel)
        error = ""
        chunks: List[Tuple[str, str]] = []
        try:
            chunks = [
                (location, chunk)
                for location, text in _segments(file)
                for chunk in split_text(text)
            ]
        except (DocumentError, OSError, UnicodeDecodeError) as e:
            error = str(e)
            report.errors.append((rel, error))
            logger.warning("Knowledge base: cannot index %s: %s", rel, e)
        for location, chunk in chunks:
            self.store.execute(
                "INSERT INTO kb_chunks (path, location, body) VALUES (?, ?, ?)",
                (rel, location, chunk),
            )
        self.store.execute(
            "INSERT OR REPLACE INTO kb_files (path, mtime, size, chunks, error) "
            "VALUES (?, ?, ?, ?, ?)", (rel, mtime, size, len(chunks), error),
        )

    def _remove(self, rel: str) -> None:
        self.store.execute("DELETE FROM kb_chunks WHERE path = ?", (rel,))
        self.store.execute("DELETE FROM kb_files WHERE path = ?", (rel,))

    def stats(self) -> dict:
        row = self.store.query(
            "SELECT COUNT(*) AS files, COALESCE(SUM(chunks), 0) AS chunks, "
            "SUM(error != '') AS errors FROM kb_files"
        )[0]
        return {"files": row["files"], "chunks": row["chunks"], "errors": row["errors"] or 0}

    def files(self) -> List[dict]:
        return [dict(r) for r in self.store.query("SELECT * FROM kb_files ORDER BY path")]

    # --- Поиск ---------------------------------------------------------------

    def search(self, query: str, limit: int = 6, refresh: bool = True) -> List[Hit]:
        if refresh:
            self.index()
        match = build_match(query)
        if not match:
            return []
        rows = self.store.query(
            "SELECT path, location, body, bm25(kb_chunks) AS score FROM kb_chunks "
            "WHERE kb_chunks MATCH ? ORDER BY score LIMIT ?", (match, limit),
        )
        return [
            Hit(r["path"], r["location"], r["body"][:MAX_RESULT_CHARS], -r["score"])
            for r in rows
        ]


def _is_bank_export(file: Path) -> bool:
    """Выписки клиент-банка для 1С - это данные для анализа, а не документы для поиска."""
    if file.suffix.lower() != ".txt":
        return False
    with file.open("rb") as handle:
        return handle.read(20) == b"1CClientBankExchange"


def build_match(query: str) -> Optional[str]:
    """Запрос FTS5: каждое слово ищется по началу (до 5 букв), слова через OR."""
    terms = []
    for word in _WORD.findall(query.lower()):
        if len(word) < 2:
            continue
        stem = word[:STEM_CHARS] if len(word) > STEM_CHARS else word
        term = f'"{stem}"*'
        if term not in terms:
            terms.append(term)
    return " OR ".join(terms) or None


def _segments(file: Path) -> List[Tuple[str, str]]:
    """Части документа с указанием места: страница PDF, лист Excel или весь файл."""
    if is_document(file):
        text = extract_text(file)
    else:
        text = file.read_text(encoding="utf-8", errors="replace")
    suffix = file.suffix.lower()
    if suffix == ".pdf":
        parts = re.split(r"--- страница (\d+) ---\n", text)
        return [(f"стр. {parts[i]}", parts[i + 1]) for i in range(1, len(parts) - 1, 2)]
    if suffix in {".xlsx", ".xlsm"}:
        parts = re.split(r"## Лист: (.+)\n", text)
        return [(f"лист «{parts[i]}»", parts[i + 1]) for i in range(1, len(parts) - 1, 2)]
    return [("", text)]


def split_text(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> List[str]:
    """Режет текст на фрагменты по абзацам; длинные абзацы - по предложениям и словам."""
    pieces: List[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        while len(paragraph) > size:
            cut = max(paragraph.rfind(". ", 0, size), paragraph.rfind(" ", 0, size))
            cut = cut + 1 if cut > size // 2 else size
            pieces.append(paragraph[:cut].strip())
            paragraph = paragraph[max(cut - overlap, 1):].strip()
        if paragraph:
            pieces.append(paragraph)

    chunks: List[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) + 2 > size:
            chunks.append(current)
            tail = current[-overlap:]
            current = tail[tail.find(" ") + 1:] if " " in tail else ""
        current = f"{current}\n\n{piece}".strip() if current else piece
    if current:
        chunks.append(current)
    return chunks
