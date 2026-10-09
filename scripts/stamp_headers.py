#!/usr/bin/env python3
# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Проставляет шапку авторства и версию во все файлы проекта.

    python scripts/stamp_headers.py          проставить или обновить шапки
    python scripts/stamp_headers.py --check  проверить (код выхода 1, если где-то нет)

Версия берётся из prizolov_os/__about__.py - меняйте её только там.
"""

import re
import runpy
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
# __about__.py читается напрямую, без импорта пакета: проверке не нужны его зависимости.
ABOUT = runpy.run_path(str(ROOT / "prizolov_os" / "__about__.py"))

LINES = [
    ABOUT["HEADER"],
    f"SPDX-FileCopyrightText: {ABOUT['__year__']} {ABOUT['__author__']} / {ABOUT['__brand__']}",
    f"SPDX-License-Identifier: {ABOUT['__license__']}",
]
HASH_SUFFIXES = {".py", ".toml", ".ini", ".yml", ".yaml", ".cfg", ".txt", ".cff", ".example"}
HASH_NAMES = {".gitignore", ".env.example"}
HTML_SUFFIXES = {".md", ".html"}
# Файлы, в которые шапку не вставляем: юридические тексты и данные.
SKIP_NAMES = {"LICENSE", "NOTICE", "AUTHORS"}
OLD_HEADER = re.compile(r"^(#|<!--) Prizolov Agent OS \S+ \| Author: ")


def style(path: Path) -> Optional[str]:
    if path.name in SKIP_NAMES:
        return None
    if path.name in HASH_NAMES or path.suffix in HASH_SUFFIXES:
        return "hash"
    if path.suffix in HTML_SUFFIXES:
        return "html"
    return None


def render(kind: str) -> List[str]:
    if kind == "hash":
        return [f"# {line}" for line in LINES]
    return [f"<!-- {LINES[0]}", *LINES[1:-1], f"{LINES[-1]} -->"]


def stamp_file(path: Path) -> bool:
    """Вставляет или обновляет шапку. Возвращает True, если файл изменился."""
    kind = style(path)
    if kind is None:
        return False
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    prefix = []
    if lines and lines[0].startswith("#!"):
        prefix, lines = [lines[0]], lines[1:]
    if lines and OLD_HEADER.match(lines[0]):
        size = len(render(kind))
        lines = lines[size:]
        if lines and not lines[0].strip():
            lines = lines[1:]
    body = "\n".join([*prefix, *render(kind), "", *lines]).rstrip("\n") + "\n"
    if body != text:
        path.write_text(body, encoding="utf-8")
        return True
    return False


def has_header(path: Path) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines()
    if lines and lines[0].startswith("#!"):
        lines = lines[1:]
    kind = style(path)
    return kind is not None and lines[: len(render(kind))] == render(kind)


def project_files(root: Path) -> List[Path]:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout
    files = [root / name for name in output.splitlines()]
    return [f for f in files if f.is_file() and style(f) is not None]


def check(root: Path = ROOT) -> List[str]:
    """Файлы без актуальной шапки (пути относительно корня)."""
    return [str(f.relative_to(root)) for f in project_files(root) if not has_header(f)]


def main(argv: List[str]) -> int:
    if "--check" in argv:
        missing = check()
        for name in missing:
            print(f"нет шапки: {name}")
        return 1 if missing else 0
    changed = [f for f in project_files(ROOT) if stamp_file(f)]
    for f in changed:
        print(f"обновлено: {f.relative_to(ROOT)}")
    print(f"Готово: {len(changed)} файлов изменено.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
