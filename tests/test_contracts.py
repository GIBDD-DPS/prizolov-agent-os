# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Помощник по договорам: сравнение версий и специалист-юрист."""

import json

from prizolov_os.agents.specialists import create_lawyer
from prizolov_os.llm import FakeLLMClient, tool_use_response
from prizolov_os.tools.contracts import compare_texts, paragraphs, word_diff

OLD = """Договор поставки № 1

1. Поставщик передаёт товар в течение 10 дней.
2. Покупатель оплачивает товар в течение 30 дней после поставки.
3. Неустойка - 0,1% за каждый день просрочки.

Стр. 1
"""
NEW = """Договор поставки № 1

1. Поставщик передаёт товар в течение 10 дней.
2. Покупатель оплачивает товар в течение 5 дней после поставки.
3. Неустойка - 0,1% за каждый день просрочки.
4. Поставщик вправе отказаться от договора в одностороннем порядке.
"""


def test_paragraphs_skip_page_numbers():
    assert "Стр. 1" not in paragraphs(OLD)
    assert paragraphs("  a   b \n\n12\n") == ["a b"]


def test_word_diff_marks_changes():
    assert word_diff("оплата 30 дней", "оплата 5 дней") == "оплата [-30-] {+5+} дней"


def test_compare_finds_changed_and_added():
    result = compare_texts(OLD, NEW)
    kinds = [c["type"] for c in result["changes"]]
    assert kinds == ["changed", "added"]
    assert "[-30-] {+5+}" in result["changes"][0]["diff"]
    assert "одностороннем" in result["changes"][1]["text"]
    assert result["paragraphs_old"] == 4 and result["paragraphs_new"] == 5
    assert 50 < result["similarity_pct"] < 100


def test_compare_identical():
    assert compare_texts(OLD, OLD)["changes_total"] == 0


def test_lawyer_compares_versions(tmp_path):
    (tmp_path / "v1.txt").write_text(OLD, encoding="utf-8")
    (tmp_path / "v2.md").write_text(NEW, encoding="utf-8")
    llm = FakeLLMClient([
        tool_use_response("compare_documents", {"old_path": "v1.txt", "new_path": "v2.md"}),
        "Срок оплаты сокращён с 30 до 5 дней - высокий риск",
    ])
    lawyer = create_lawyer(llm=llm, workspace_dir=tmp_path)
    result = lawyer.run("Сравни версии договора")
    assert "высокий риск" in result.text
    sent = json.dumps(llm.calls[1]["messages"], ensure_ascii=False)
    assert "untrusted_data" in sent and "{+5+}" in sent
    assert "compare_documents" in lawyer.tools and "write_file" in lawyer.tools
    assert "юрист" in lawyer.system_prompt
