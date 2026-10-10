# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Уроки из опыта: превращает оценку пользователя в правило для агента."""

from dataclasses import dataclass
from typing import List, Optional, Sequence

from ..llm import LLMClient, Usage
from ..memory import Lesson
from .structured import ask_json, object_schema

EXTRACTOR_SYSTEM = """Ты помогаешь ИИ-системе Prizolov Agent OS учиться на \
обратной связи пользователя.

По задаче, ответу системы и оценке пользователя сформулируй один урок - общее \
правило, которое улучшит будущие ответы в похожих задачах. Правило должно быть \
конкретным, проверяемым, в повелительном наклонении, одним-двумя предложениями.
Укажи агента, к которому правило относится больше всего (director - если оно про \
итоговый ответ или распределение задач).
Если обратная связь не содержит обобщаемого урока, верни пустую строку в lesson."""


@dataclass
class ExtractedLesson:
    agent: str
    text: str
    usage: Usage


class LessonExtractor:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def from_feedback(
        self,
        task: str,
        answer: str,
        positive: bool,
        comment: str,
        agents: Sequence[str],
    ) -> Optional[ExtractedLesson]:
        schema = object_schema({
            "agent": {"type": "string", "enum": list(agents)},
            "lesson": {"type": "string"},
        })
        verdict = "положительная" if positive else "отрицательная"
        prompt = (
            f"<задача>\n{task}\n</задача>\n\n<ответ>\n{answer}\n</ответ>\n\n"
            f"<оценка_пользователя>{verdict}</оценка_пользователя>\n"
            f"<комментарий>{comment or '(без комментария)'}</комментарий>"
        )
        data, usage = ask_json(self.llm, EXTRACTOR_SYSTEM, prompt, schema)
        if not data or not str(data.get("lesson", "")).strip():
            return None
        agent = str(data["agent"]) if data.get("agent") in agents else agents[0]
        return ExtractedLesson(agent=agent, text=str(data["lesson"]).strip(), usage=usage)


def format_lessons(lessons: List[Lesson]) -> str:
    """Текст с уроками для добавления к запросу агента."""
    if not lessons:
        return ""
    items = "\n".join(f"- {lesson.text}" for lesson in lessons)
    return f"<уроки_из_прошлого_опыта>\nУчитывай эти правила:\n{items}\n</уроки_из_прошлого_опыта>"
