"""Улучшение системного промпта агента на основе накопленных уроков."""

import difflib
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from ..llm import LLMClient, Usage
from ..memory import Lesson
from .structured import ask_json, object_schema

IMPROVER_SYSTEM = """Ты улучшаешь системные промпты агентов Prizolov Agent OS.

Тебе дают текущий промпт агента и уроки, накопленные из обратной связи. Встрой \
уроки в промпт:
- сохрани назначение, структуру и все действующие правила, если урок им прямо не \
противоречит;
- формулируй кратко и конкретно, объединяй похожие уроки, не дублируй правила;
- не добавляй ничего, что не следует из уроков.
В changes перечисли, что изменилось и почему."""

IMPROVEMENT_SCHEMA = object_schema({
    "prompt": {"type": "string"},
    "changes": {"type": "array", "items": {"type": "string"}},
})


@dataclass
class PromptProposal:
    agent: str
    prompt: str
    changes: List[str]
    diff: str
    usage: Usage = field(default_factory=Usage)


class PromptImprover:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def propose(
        self, agent: str, current_prompt: str, lessons: Sequence[Lesson]
    ) -> Optional[PromptProposal]:
        if not lessons:
            raise ValueError(f"У агента {agent} нет уроков, улучшать нечего")
        items = "\n".join(f"- {lesson.text}" for lesson in lessons)
        prompt = (
            f"<агент>{agent}</агент>\n\n<текущий_промпт>\n{current_prompt}\n</текущий_промпт>"
            f"\n\n<уроки>\n{items}\n</уроки>"
        )
        data, usage = ask_json(self.llm, IMPROVER_SYSTEM, prompt, IMPROVEMENT_SCHEMA, 16000)
        if not data or not str(data.get("prompt", "")).strip():
            return None
        new_prompt = str(data["prompt"]).strip()
        return PromptProposal(
            agent=agent,
            prompt=new_prompt,
            changes=[str(c) for c in data.get("changes") or []],
            diff=prompt_diff(current_prompt, new_prompt),
            usage=usage,
        )


def prompt_diff(old: str, new: str) -> str:
    return "\n".join(difflib.unified_diff(
        old.splitlines(), new.splitlines(), "текущий", "предложенный", lineterm=""
    ))
