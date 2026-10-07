"""Самопроверка: критик оценивает ответ и предлагает правки."""

from dataclasses import dataclass, field
from typing import List, Sequence

from ..llm import LLMClient, Usage
from .structured import ask_json, object_schema

CRITIC_SYSTEM = """Ты - строгий и справедливый проверяющий ответов ИИ-системы \
Prizolov Agent OS. Ты не пишешь ответ сам, а оцениваешь готовый.

Критерии:
1. Ответ полностью решает задачу пользователя.
2. Цифры и факты подтверждаются данными, которые система получила от специалистов \
(они приведены ниже). Выдуманные или искажённые данные - серьёзная ошибка.
3. Есть нужные оговорки: неопределённость прогнозов, источники, для рыночной \
аналитики - что это не инвестиционная рекомендация.
4. Ответ ясный, структурированный, без лишнего.

score: 1-10, где 10 - улучшать нечего, 7 - приемлемо, ниже 7 - нужно исправить.
issues: конкретные замечания, что исправить; пустой список, если исправлять нечего.
lesson: если ошибка системная и повторится в других задачах, сформулируй общее \
правило для системы одним предложением в повелительном наклонении; иначе пустая строка."""

REVIEW_SCHEMA = object_schema({
    "score": {"type": "integer"},
    "issues": {"type": "array", "items": {"type": "string"}},
    "lesson": {"type": "string"},
})

MAX_EVIDENCE_CHARS = 20_000


@dataclass
class Review:
    score: int
    issues: List[str] = field(default_factory=list)
    lesson: str = ""
    usage: Usage = field(default_factory=Usage)


class Critic:
    def __init__(self, llm: LLMClient, threshold: int = 7) -> None:
        self.llm = llm
        self.threshold = threshold

    def review(self, task: str, answer: str, evidence: Sequence[str] = ()) -> Review:
        """Оценивает ответ. Если проверка не удалась, ответ считается приемлемым."""
        data, usage = ask_json(
            self.llm, CRITIC_SYSTEM, _prompt(task, answer, evidence), REVIEW_SCHEMA
        )
        if data is None:
            return Review(score=10, usage=usage)
        score = data.get("score")
        return Review(
            score=max(1, min(10, score)) if isinstance(score, int) else 10,
            issues=[str(i) for i in data.get("issues") or [] if str(i).strip()],
            lesson=str(data.get("lesson") or "").strip(),
            usage=usage,
        )

    def needs_revision(self, review: Review) -> bool:
        return review.score < self.threshold and bool(review.issues)


def revision_request(review: Review) -> str:
    issues = "\n".join(f"- {issue}" for issue in review.issues)
    return (
        "[Самопроверка] Проверка ответа выявила замечания:\n"
        f"{issues}\n\n"
        "Исправь ответ с учётом замечаний. Если не хватает данных, поручи их получение "
        "специалистам. Верни полный исправленный ответ для пользователя."
    )


def _prompt(task: str, answer: str, evidence: Sequence[str]) -> str:
    parts, budget = [], MAX_EVIDENCE_CHARS
    for item in evidence:
        chunk = item[:budget]
        parts.append(chunk)
        budget -= len(chunk)
        if budget <= 0:
            break
    data = "\n\n---\n\n".join(parts) if parts else "(специалисты не привлекались)"
    return (
        f"<задача_пользователя>\n{task}\n</задача_пользователя>\n\n"
        f"<данные_от_специалистов>\n{data}\n</данные_от_специалистов>\n\n"
        f"<ответ_системы>\n{answer}\n</ответ_системы>"
    )
