# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Договоры: сравнение версий документа (что добавили, удалили, изменили)."""

import difflib
import re
from typing import Any, Dict, List

from .base import Tool, make_schema
from .builtin import Workspace

MAX_CHANGES = 80
MAX_PARAGRAPH = 1200


def paragraphs(text: str) -> List[str]:
    """Абзацы без лишних пробелов; пустые строки и разрывы страниц убраны."""
    result = []
    for line in text.splitlines():
        line = " ".join(line.split())
        if line and not re.fullmatch(r"[-=_—\s\d]*(стр\.?\s*\d+)?", line, flags=re.I):
            result.append(line)
    return result


def word_diff(old: str, new: str) -> str:
    """Изменения внутри абзаца: [-удалено-] {+добавлено+}."""
    a, b = old.split(), new.split()
    out: List[str] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.extend(a[i1:i2])
        if op in ("delete", "replace"):
            out.append("[-" + " ".join(a[i1:i2]) + "-]")
        if op in ("insert", "replace"):
            out.append("{+" + " ".join(b[j1:j2]) + "+}")
    return " ".join(out)


def compare_texts(old: str, new: str) -> Dict[str, Any]:
    """Сравнивает две версии текста по абзацам."""
    a, b = paragraphs(old), paragraphs(new)
    changes: List[Dict[str, Any]] = []
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue
        if op == "replace" and (i2 - i1) == (j2 - j1):
            for k in range(i2 - i1):
                changes.append({"type": "changed", "old_index": i1 + k + 1,
                                "diff": word_diff(a[i1 + k], b[j1 + k])[:MAX_PARAGRAPH]})
            continue
        for k in range(i1, i2):
            changes.append({"type": "removed", "old_index": k + 1, "text": a[k][:MAX_PARAGRAPH]})
        for k in range(j1, j2):
            changes.append({"type": "added", "new_index": k + 1, "text": b[k][:MAX_PARAGRAPH]})
    return {
        "paragraphs_old": len(a),
        "paragraphs_new": len(b),
        "similarity_pct": round(matcher.ratio() * 100, 1),
        "changes_total": len(changes),
        "changes": changes[:MAX_CHANGES],
        "truncated": len(changes) > MAX_CHANGES,
    }


def contract_tools(workspace: Workspace) -> List[Tool]:
    def compare_documents(old_path: str, new_path: str) -> Dict[str, Any]:
        result = compare_texts(workspace.read_file(old_path), workspace.read_file(new_path))
        result["note"] = (
            "changed.diff: [-удалено-] {+добавлено+}. Обрати внимание на изменения сумм, "
            "сроков, неустоек, ответственности, порядка оплаты и расторжения."
        )
        return result

    return [
        Tool(
            name="compare_documents",
            description=(
                "Сравнивает две версии документа (договора, ТЗ) из рабочей папки: PDF, Word, "
                "TXT, MD. Возвращает добавленные, удалённые и изменённые абзацы; изменения "
                "внутри абзаца помечены [-было-] {+стало+}."
            ),
            input_schema=make_schema({
                "old_path": {"type": "string", "description": "Прежняя версия"},
                "new_path": {"type": "string", "description": "Новая версия"},
            }),
            handler=compare_documents,
            untrusted=True,
        ),
    ]


__all__ = ["compare_texts", "contract_tools", "paragraphs", "word_diff"]
