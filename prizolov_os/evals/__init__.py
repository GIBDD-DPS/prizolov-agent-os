# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Проверка агентов на настоящей модели (evals).

Каждая проверка - задача, как от пользователя, и ожидания к решению:
- кому Директор должен поручить задачу и какие инструменты вызвать;
- какие факты должны быть в ответе (регулярные выражения) и каких быть не должно;
- критерии для модели-оценщика (необязательно).

Модульные тесты идут на подставной модели и проверяют код. Эти проверки
показывают качество самих ответов: стало лучше или хуже после правки промпта
или смены модели. Они тратят токены, поэтому запускаются вручную
(`prizolov eval`) или по расписанию в CI.
"""

import json
import math
import random
import re
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from .. import events as ev
from ..core.kernel import Kernel
from ..improvement.structured import ask_json, object_schema
from ..llm import LLMClient, LLMError
from ..market.data import PriceSeries
from ..memory import Store

# Демо-файлы из папки examples/ репозитория (ссылка вида "examples:demo_prices.csv").
EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"
JUDGE_PASS_SCORE = 7


class EvalError(Exception):
    """Проверку нельзя запустить (нет демо-файлов, неизвестный id)."""


@dataclass
class EvalCase:
    """Задача и ожидания к её решению.

    expect_agents / expect_tools: каждый элемент должен встретиться; "a|b" - любой из.
    must_match / must_not_match: регулярные выражения по ответу (без учёта регистра,
    пробелы внутри чисел убраны: «463 300» сравнивается как «463300»).
    """

    id: str
    title: str
    task: str
    files: Dict[str, str] = field(default_factory=dict)
    expect_agents: Sequence[str] = ()
    expect_tools: Sequence[str] = ()
    must_match: Sequence[str] = ()
    must_not_match: Sequence[str] = ()
    rubric: str = ""


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class EvalResult:
    case_id: str
    title: str
    passed: bool
    checks: List[Check]
    answer: str = ""
    agents: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    judge_score: Optional[int] = None
    judge_reason: str = ""
    cost_usd: float = 0.0
    seconds: float = 0.0
    error: str = ""


class DemoMarket:
    """Котировки без сети: детерминированные ряды, чтобы проверки оценивали агентов,
    а не доступность источников."""

    START = {
        "GOLD": 7000.0, "SILVER": 85.0, "USD": 90.0, "EUR": 98.0, "CNY": 12.5,
        "SBER": 300.0, "LKOH": 7000.0, "GAZP": 150.0, "BTC-USD": 60000.0,
        "AAPL": 220.0, "GC=F": 2400.0,
    }

    def history(self, source: str, symbol: str, days: int) -> PriceSeries:
        symbol = symbol.upper()
        rng = random.Random(sum(map(ord, symbol)))
        prices = [self.START.get(symbol, 100.0)]
        for _ in range(days):
            prices.append(prices[-1] * math.exp(rng.gauss(0.0003, 0.012)))
        start = date.today() - timedelta(days=len(prices) - 1)
        dates = [start + timedelta(i) for i in range(len(prices))]
        currency = "USD" if source == "yahoo" else "RUB"
        return PriceSeries(source, symbol, currency, dates, prices)


def normalize(text: str) -> str:
    """Нижний регистр, ё → е, без пробелов внутри чисел."""
    text = text.lower().replace("ё", "е")
    return re.sub(r"(?<=\d)[\s  ](?=\d{3}\b)", "", text)


def _expected(items: Sequence[str], seen: Sequence[str], what: str) -> List[Check]:
    checks = []
    for item in items:
        options = item.split("|")
        ok = any(o in seen for o in options)
        checks.append(Check(f"{what}: {item}", ok, "" if ok else f"было: {', '.join(seen) or '-'}"))
    return checks


def rule_checks(case: EvalCase, answer: str, agents: Sequence[str],
                tools: Sequence[str]) -> List[Check]:
    text = normalize(answer)
    checks = _expected(case.expect_agents, agents, "поручено")
    checks += _expected(case.expect_tools, tools, "инструмент")
    for pattern in case.must_match:
        ok = re.search(pattern, text, re.IGNORECASE | re.MULTILINE) is not None
        checks.append(Check(f"есть в ответе: {pattern}", ok))
    for pattern in case.must_not_match:
        ok = re.search(pattern, text, re.IGNORECASE | re.MULTILINE) is None
        checks.append(Check(f"нет в ответе: {pattern}", ok))
    return checks


JUDGE_SYSTEM = (
    "Ты строгий и беспристрастный проверяющий ответов ИИ-ассистента для малого бизнеса. "
    "Оцени ответ только по перечисленным критериям. Не додумывай за ответ то, чего в нём "
    "нет. passed = true, только если выполнены все критерии. score - от 1 до 10."
)
JUDGE_SCHEMA = object_schema({
    "score": {"type": "integer"},
    "passed": {"type": "boolean"},
    "reason": {"type": "string"},
})


def judge(llm: LLMClient, case: EvalCase, answer: str) -> Check:
    prompt = (
        f"<задача_пользователя>\n{case.task}\n</задача_пользователя>\n\n"
        f"<ответ_ассистента>\n{answer}\n</ответ_ассистента>\n\n"
        f"<критерии>\n{case.rubric}\n</критерии>\n\n"
        "Кратко объясни оценку в reason (одно-два предложения на русском)."
    )
    data, _ = ask_json(llm, JUDGE_SYSTEM, prompt, JUDGE_SCHEMA, max_tokens=2000)
    if not data:
        return Check("оценщик", False, "оценщик не дал ответа")
    score = int(data.get("score", 0))
    ok = bool(data.get("passed")) and score >= JUDGE_PASS_SCORE
    return Check(f"оценщик: {score}/10", ok, str(data.get("reason", "")))


def _prepare_workspace(case: EvalCase, root: Path) -> None:
    for name, content in case.files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if content.startswith("examples:"):
            source = EXAMPLES_DIR / content.split(":", 1)[1]
            if not source.is_file():
                raise EvalError(
                    f"Нет демо-файла {source}. Проверки запускаются из клона репозитория."
                )
            shutil.copyfile(source, target)
        else:
            target.write_text(content, encoding="utf-8")


KernelFactory = Callable[..., Kernel]


def run_case(
    case: EvalCase,
    *,
    kernel_factory: KernelFactory = Kernel.create,
    judge_llm: Optional[LLMClient] = None,
    task_limit_usd: float = 2.0,
) -> EvalResult:
    """Решает задачу в чистой рабочей папке с пустой памятью и проверяет ответ.

    Запись файлов и расписание отклоняются: проверки ничего не меняют.
    """
    started = time.monotonic()
    agents: List[str] = []
    tools: List[str] = []
    with tempfile.TemporaryDirectory(prefix="prizolov-eval-") as tmp:
        workspace = Path(tmp)
        _prepare_workspace(case, workspace)
        kernel = kernel_factory(
            approver=lambda name, params: False, workspace_dir=workspace, store=Store(),
            market=DemoMarket(), self_check="off", trace=False,
        )
        if kernel.budget is not None:
            kernel.budget.task_limit_usd = task_limit_usd

        def listen(event: ev.Event) -> None:
            if event.type == ev.DELEGATION_START:
                agents.append(str(event.data.get("specialist", "")))
            elif event.type == ev.TOOL_CALL:
                tools.append(str(event.data.get("tool", "")))

        kernel.events.subscribe(listen)
        try:
            answer = kernel.run(case.task).text
        except LLMError as e:
            return EvalResult(case.id, case.title, False, [], error=str(e),
                              agents=agents, tools=tools,
                              cost_usd=_spent(kernel), seconds=time.monotonic() - started)
        finally:
            kernel.store.close()
    checks = rule_checks(case, answer, agents, tools)
    result = EvalResult(case.id, case.title, False, checks, answer=answer, agents=agents,
                        tools=tools, cost_usd=_spent(kernel))
    if case.rubric and judge_llm is not None:
        verdict = judge(judge_llm, case, answer)
        checks.append(verdict)
        match = re.search(r"\d+", verdict.name)
        result.judge_score = int(match.group()) if match else None
        result.judge_reason = verdict.detail
    result.passed = all(c.ok for c in checks)
    result.seconds = time.monotonic() - started
    return result


def _spent(kernel: Kernel) -> float:
    return kernel.budget.task_spent_usd if kernel.budget is not None else 0.0


def select(cases: Sequence[EvalCase], ids: Sequence[str]) -> List[EvalCase]:
    if not ids:
        return list(cases)
    known = {c.id: c for c in cases}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise EvalError(
            f"Нет проверок: {', '.join(unknown)}. Список: prizolov eval --list"
        )
    return [known[i] for i in ids]


def run_all(
    cases: Sequence[EvalCase],
    *,
    kernel_factory: KernelFactory = Kernel.create,
    judge_llm: Optional[LLMClient] = None,
    max_usd: float = 10.0,
    on_result: Optional[Callable[[EvalResult], None]] = None,
) -> List[EvalResult]:
    """Прогоняет проверки по очереди; останавливается, если потрачено max_usd."""
    results: List[EvalResult] = []
    spent = 0.0
    for case in cases:
        if max_usd and spent >= max_usd:
            results.append(EvalResult(
                case.id, case.title, False, [],
                error=f"Пропущено: потрачено ${spent:.2f} из лимита ${max_usd:.2f}",
            ))
            continue
        result = run_case(case, kernel_factory=kernel_factory, judge_llm=judge_llm)
        spent += result.cost_usd
        results.append(result)
        if on_result is not None:
            on_result(result)
    return results


def summary(results: Sequence[EvalResult]) -> Dict[str, Any]:
    passed = sum(r.passed for r in results)
    return {
        "total": len(results),
        "passed": passed,
        "pass_rate_pct": round(passed / len(results) * 100, 1) if results else 0.0,
        "cost_usd": round(sum(r.cost_usd for r in results), 4),
        "seconds": round(sum(r.seconds for r in results), 1),
    }


def to_markdown(results: Sequence[EvalResult], model: str = "") -> str:
    from ..__about__ import SIGNATURE

    s = summary(results)
    lines = [
        f"# Проверка агентов — {datetime.now():%d.%m.%Y %H:%M}",
        "",
        f"Модель: {model or '-'}. Пройдено {s['passed']} из {s['total']} "
        f"({s['pass_rate_pct']}%), стоимость ${s['cost_usd']:.2f}, время {s['seconds']} с.",
        "",
        "| Проверка | Итог | Оценщик | $ | Что не так |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        problems = r.error or "; ".join(
            f"{c.name}" + (f" ({c.detail})" if c.detail else "") for c in r.checks if not c.ok
        )
        score = "-" if r.judge_score is None else f"{r.judge_score}/10"
        lines.append(
            f"| {r.case_id}: {r.title} | {'✅' if r.passed else '❌'} | {score} | "
            f"{r.cost_usd:.3f} | {problems.replace('|', '/') or '-'} |"
        )
    lines += ["", f"<sub>{SIGNATURE}</sub>", ""]
    return "\n".join(lines)


def to_json(results: Sequence[EvalResult], model: str = "") -> str:
    return json.dumps(
        {"model": model, "summary": summary(results), "results": [asdict(r) for r in results]},
        ensure_ascii=False, indent=2,
    )


__all__ = [
    "Check", "DemoMarket", "EvalCase", "EvalError", "EvalResult", "judge", "normalize",
    "rule_checks", "run_all", "run_case", "select", "summary", "to_json", "to_markdown",
]
