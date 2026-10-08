# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Авторство: шапки файлов, лицензия, метки в работающей программе."""

import io
import subprocess
import sys
from pathlib import Path

import pytest
from rich.console import Console

import prizolov_os
from cli.app import ChatApp
from prizolov_os.__about__ import HEADER, PROJECT_ID, SIGNATURE, USER_AGENT, __version__
from prizolov_os.agents import create_specialists
from prizolov_os.core.kernel import Kernel
from prizolov_os.llm import FakeLLMClient
from prizolov_os.memory import Store
from prizolov_os.tools import Workspace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import stamp_headers  # noqa: E402


def test_header_format():
    assert HEADER == (
        f"Prizolov Agent OS {__version__} | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026"
    )
    assert prizolov_os.__author__ == "Dm.Andreyanov"
    assert prizolov_os.__brand__ == "Prizolov Lab"


def test_every_file_has_current_header():
    missing = stamp_headers.check(ROOT)
    assert missing == [], "Нет актуальной шапки авторства: " + ", ".join(missing)


def test_stamp_is_idempotent_and_keeps_shebang(tmp_path):
    script = tmp_path / "tool.py"
    script.write_text("#!/usr/bin/env python3\nprint('hi')\n")
    stamp_headers.stamp_file(script)
    once = script.read_text()
    stamp_headers.stamp_file(script)
    assert script.read_text() == once
    lines = once.splitlines()
    assert lines[0] == "#!/usr/bin/env python3"
    assert lines[1] == f"# {HEADER}"
    assert "SPDX-License-Identifier: Apache-2.0" in lines[3]


def test_stamp_replaces_old_version(tmp_path):
    file = tmp_path / "a.py"
    old = "# Prizolov Agent OS 0.1.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026\n"
    file.write_text(
        old
        + "# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab\n"
        + "# SPDX-License-Identifier: Apache-2.0\n\nx = 1\n"
    )
    stamp_headers.stamp_file(file)
    text = file.read_text()
    assert text.count("Prizolov Agent OS") == 1 and __version__ in text
    assert text.endswith("x = 1\n")


def test_markdown_header_is_comment(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Заголовок\n")
    stamp_headers.stamp_file(doc)
    assert doc.read_text().startswith(f"<!-- {HEADER}")


def test_license_and_notice():
    assert "Apache License" in (ROOT / "LICENSE").read_text()
    notice = (ROOT / "NOTICE").read_text()
    assert "Dm.Andreyanov / Prizolov Lab" in notice and PROJECT_ID in notice
    assert PROJECT_ID in (ROOT / "CITATION.cff").read_text()


def test_version_flag():
    out = subprocess.run(
        [sys.executable, "-m", "cli.main", "--version"], cwd=ROOT, capture_output=True, text=True
    ).stdout
    assert HEADER in out and PROJECT_ID in out


def test_store_carries_author_mark():
    meta = Store().meta()
    assert meta["author"] == "Dm.Andreyanov"
    assert meta["brand"] == "Prizolov Lab"
    assert meta["project_id"] == PROJECT_ID
    assert meta["version"] == __version__


def test_agents_know_their_author(tmp_path):
    kernel = Kernel.create(llm=FakeLLMClient(), store=Store(), workspace_dir=tmp_path)
    for agent in kernel.agents.values():
        assert "Dm.Andreyanov" in agent.system_prompt, agent.name
    for agent in create_specialists(llm=FakeLLMClient(), workspace_dir=tmp_path).values():
        assert "Prizolov Lab" in agent.system_prompt


def test_user_agent_identifies_project():
    from prizolov_os.market import data

    assert data.USER_AGENT == USER_AGENT
    assert "Prizolov Lab" in USER_AGENT and PROJECT_ID in USER_AGENT


@pytest.mark.parametrize("name, signed", [
    ("report.md", True), ("notes.txt", True), ("page.html", True),
    ("data.csv", False), ("data.json", False),
])
def test_agent_files_signed(tmp_path, name, signed):
    ws = Workspace(tmp_path, sign_output=True)
    ws.write_file(name, "содержимое")
    ws.write_file(name, ws.read_file(name))  # повторная запись не дублирует подпись
    text = (tmp_path / name).read_text()
    assert (SIGNATURE in text) is signed
    assert text.count(SIGNATURE) == (1 if signed else 0)


def test_signature_can_be_disabled(tmp_path):
    Workspace(tmp_path, sign_output=False).write_file("a.md", "x")
    assert (tmp_path / "a.md").read_text() == "x"


def test_chat_banner(tmp_path):
    out = io.StringIO()
    kernel = Kernel.create(llm=FakeLLMClient(), store=Store(), workspace_dir=tmp_path)
    app = ChatApp(kernel, Console(file=out, width=150, color_system=None),
                  lambda _: (_ for _ in ()).throw(EOFError()))
    app.loop()
    assert HEADER in out.getvalue()
