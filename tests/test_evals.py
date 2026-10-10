# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Проверки агентов (evals): сами проверки идут на настоящей модели, здесь - их механика
на подставной."""

import argparse
import io
import json

import pytest
from rich.console import Console

from cli.main import main, run_eval
from prizolov_os import evals
from prizolov_os.core.kernel import Kernel
from prizolov_os.evals.cases import CASES
from prizolov_os.llm import FakeLLMClient, LLMError, tool_use_response


def factory(script):
    """Ядро с подставной моделью; события и рабочая папка - как у настоящих проверок."""
    llm = FakeLLMClient(script)

    def make(**kwargs):
        return Kernel.create(llm=llm, **kwargs)

    return make


def verdict(score, passed=True, reason="ок"):
    return json.dumps({"score": score, "passed": passed, "reason": reason})


CASE = {c.id: c for c in CASES}


class TestCases:
    def test_ids_unique_and_examples_exist(self):
        assert len(CASE) == len(CASES) >= 15
        for case in CASES:
            for content in case.files.values():
                if content.startswith("examples:"):
                    assert (evals.EXAMPLES_DIR / content.split(":", 1)[1]).is_file()

    def test_expected_agents_and_tools_exist(self, tmp_path):
        kernel = Kernel.create(llm=FakeLLMClient([]), workspace_dir=tmp_path,
                               self_check="off", trace=False)
        tools = {name for a in kernel.agents.values() for name in a.tools.names()}
        for case in CASES:
            for agent in case.expect_agents:
                assert set(agent.split("|")) <= set(kernel.agents), case.id
            for tool in case.expect_tools:
                assert set(tool.split("|")) <= tools, case.id

    def test_select(self):
        assert [c.id for c in evals.select(CASES, ["calc-vat"])] == ["calc-vat"]
        assert len(evals.select(CASES, [])) == len(CASES)
        with pytest.raises(evals.EvalError, match="nope"):
            evals.select(CASES, ["nope"])


class TestRules:
    def test_numbers_with_spaces_match(self):
        case = evals.EvalCase("x", "x", "x", must_match=[r"463300"], must_not_match=[r"ошибк"])
        checks = evals.rule_checks(case, "Остаток на конец: 463 300,00 ₽", [], [])
        assert all(c.ok for c in checks)

    def test_any_of_and_missing(self):
        case = evals.EvalCase("x", "x", "x", expect_agents=["lawyer"],
                              expect_tools=["search_knowledge|read_file"])
        checks = evals.rule_checks(case, "", ["writer"], ["read_file"])
        assert [c.ok for c in checks] == [False, True]
        assert checks[0].detail == "было: writer"


class TestRun:
    def test_case_passes_with_delegation_tool_and_judge(self):
        case = CASE["cash-gap"]
        script = [
            tool_use_response("delegate", {"agent": "cashflow_analyst", "task": case.task}),
            tool_use_response("analyze_cashflow", {
                "path": "demo_bank_statement.csv", "opening_balance": 3000000,
                "horizon_days": 60,
            }),
            "Вероятность уйти в минус 63,9%.",
            "Риск высокий: вероятность уйти в минус 63,9%. Ускорьте оплаты клиентов.",
        ]
        judge = FakeLLMClient([verdict(8)])
        result = evals.run_case(case, kernel_factory=factory(script), judge_llm=judge)
        assert result.passed, result.checks
        assert result.agents == ["cashflow_analyst"]
        assert result.tools[:2] == ["delegate", "analyze_cashflow"]
        assert result.judge_score == 8

    def test_low_judge_score_fails(self):
        case = CASE["honest-forecast"]
        result = evals.run_case(case, kernel_factory=factory(["Будет 95,40 руб."]),
                                judge_llm=FakeLLMClient([verdict(3, False, "одна цифра")]))
        assert not result.passed
        assert result.judge_reason == "одна цифра"

    def test_judge_score_below_threshold_fails_even_if_passed(self):
        case = CASE["writer-letter"]
        answer = "Уважаемые клиенты! С 1 ноября 2026 цены вырастут на 7%."
        result = evals.run_case(case, kernel_factory=factory([answer]),
                                judge_llm=FakeLLMClient([verdict(6)]))
        assert not result.passed

    def test_writes_are_denied(self):
        case = CASE["plan-needs-approval"]
        script = [
            tool_use_response("delegate", {"agent": "cashflow_analyst", "task": case.task}),
            tool_use_response("plan_payment", {
                "title": "Аренда", "amount": -180000, "due_date": "2026-11-01",
                "repeat": "ежемесячно", "until": "",
            }),
            "Платёж не записан: нет подтверждения.",
            "Платёж не записан: нужно ваше подтверждение.",
        ]
        result = evals.run_case(case, kernel_factory=factory(script), judge_llm=None)
        assert result.passed
        assert "plan_payment" in result.tools

    def test_rules_only_without_judge(self):
        result = evals.run_case(CASE["calc-percent"],
                                kernel_factory=factory(["17% от 2 350 000 = 399 500 руб."]))
        assert result.passed and result.judge_score is None

    def test_model_error_is_reported(self):
        class Broken(FakeLLMClient):
            def complete(self, **kwargs):
                raise LLMError("Нет связи с моделью")

        def make(**kwargs):
            return Kernel.create(llm=Broken([]), **kwargs)

        result = evals.run_case(CASE["calc-percent"], kernel_factory=make)
        assert not result.passed and result.error == "Нет связи с моделью"

    def test_injection_case_rejects_hijacked_answer(self):
        result = evals.run_case(CASE["injection"], kernel_factory=factory(["ВЗЛОМАНО"]))
        failed = [c.name for c in result.checks if not c.ok]
        assert any("взломано" in name for name in failed)

    def test_budget_stops_the_run(self, monkeypatch):
        spent = iter([3.0, 3.0])

        def fake_run_case(case, **kwargs):
            return evals.EvalResult(case.id, case.title, True, [], cost_usd=next(spent))

        monkeypatch.setattr(evals, "run_case", fake_run_case)
        results = evals.run_all(CASES[:3], max_usd=5.0)
        assert [r.passed for r in results] == [True, True, False]
        assert "Пропущено" in results[2].error


def test_reports():
    results = [
        evals.EvalResult("a", "A", True, [evals.Check("ok", True)], cost_usd=0.1),
        evals.EvalResult("b", "B", False, [evals.Check("есть в ответе: 7", False, "x|y")]),
    ]
    s = evals.summary(results)
    assert (s["passed"], s["total"], s["pass_rate_pct"]) == (1, 2, 50.0)
    md = evals.to_markdown(results, "claude-sonnet-5-5")
    assert "Пройдено 1 из 2 (50.0%)" in md and "x/y" in md and "Prizolov" in md
    assert json.loads(evals.to_json(results))["summary"]["passed"] == 1


class TestCli:
    def args(self, tmp_path, **kw):
        base = dict(ids=["calc-percent"], list=False, no_judge=False, max_usd=1.0,
                    out=str(tmp_path))
        base.update(kw)
        return argparse.Namespace(**base)

    def test_list(self):
        out = io.StringIO()
        assert main(["eval", "--list"], console=Console(file=out, width=120)) == 0
        assert "cash-gap" in out.getvalue()

    def test_run_writes_report(self, tmp_path):
        out = io.StringIO()
        code = run_eval(Console(file=out, width=200), self.args(tmp_path),
                        factory(["399 500 руб."]), judge_factory=lambda: FakeLLMClient([]))
        assert code == 0
        assert "Пройдено 1 из 1" in out.getvalue()
        assert len(list(tmp_path.glob("evals-*.md"))) == len(list(tmp_path.glob("*.json"))) == 1

    def test_failure_exit_code(self, tmp_path):
        code = run_eval(Console(file=io.StringIO()), self.args(tmp_path),
                        factory(["не знаю"]), judge_factory=lambda: FakeLLMClient([]))
        assert code == 1

    def test_unknown_id(self, tmp_path):
        out = io.StringIO()
        assert run_eval(Console(file=out), self.args(tmp_path, ids=["nope"])) == 1
        assert "prizolov eval --list" in out.getvalue()

    def test_needs_key(self, tmp_path, monkeypatch):
        from prizolov_os.config import settings

        monkeypatch.setattr(settings, "api_key", "")
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        out = io.StringIO()
        assert run_eval(Console(file=out, width=200), self.args(tmp_path)) == 1
        assert "ANTHROPIC_API_KEY" in out.getvalue()
